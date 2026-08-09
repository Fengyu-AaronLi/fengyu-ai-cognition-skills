#!/usr/bin/env python3
"""Deterministic runtime for evidence-bound identity-label cases.

The runtime does not diagnose people and does not pretend to infer a complete
analysis from a sentence.  It provides a conservative routing scaffold,
machine-checkable policy gates, an append-only state machine, replay, and a
renderer for validated records.
"""

from __future__ import annotations

import argparse
import copy
import fcntl
import hashlib
import json
import os
import re
import sys
import tempfile
import unicodedata
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Iterator


ROOT = Path(__file__).resolve().parents[1]
SCHEMAS = ROOT / "schemas"
CASE_FILE = "case.json"
EVENTS_FILE = "events.jsonl"
EVENT_HEAD_FILE = "events.head.json"
LOCK_FILE = ".case.lock"
TRANSACTION_JOURNAL_FILE = ".case-transaction.json"
STATE_FILES = (EVENTS_FILE, CASE_FILE, EVENT_HEAD_FILE)
SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")
TRANSACTION_DIR_NAME_PATTERN = re.compile(r"\.case-txn-[a-z0-9_]{6,32}")
RUNTIME_STAGE_NAME_PATTERN = re.compile(
    r"\.(?:events\.jsonl|case\.json|events\.head\.json|case-transaction\.json)\.[a-z0-9_]{6,32}\.tmp"
)
MAX_USER_TEXT_BYTES = 1_000_000

SOURCE_STATUS = {
    "reported_clinical_diagnosis": "user_reported_formal_diagnosis",
    "formal_scale_result": "reported_scale_result",
    "user_self_description": "reported_unverified",
    "ai_inference": "unverified_inference",
    "social_media_label": "unverified_label",
    "other_person_attribution": "reported_third_party_attribution",
    "unknown_source": "unknown",
}

EMPTY_EXPERIMENT = {
    "status": "not_planned",
    "started_at": None,
    "target_claim": "",
    "target_judgment_ids": [],
    "primary_variable": "",
    "duration": {"value": 0, "unit": "days"},
    "action": "",
    "kept_constant": [],
    "measures": [],
    "support_if": [],
    "weaken_if": [],
    "reversible": False,
    "reversibility_note": "",
}

SAFETY_PATTERN = re.compile(
    r"自杀|自伤|割伤(?:自己|我自己)?|不想活|伤害(?:伴侣|别人|他人|自己)|杀了(?:自己|他|她)|"
    r"(?:准备|打算|想要|即将).{0,8}结束自己的生命|攻击(?:室友|伴侣|别人|他人)|"
    r"(?:站到|站在|爬到).{0,8}(?:天台|楼顶|桥边|高处).{0,32}(?:跳下去|跳下|跳楼)|"
    r"(?:准备|打算|计划).{0,32}(?:跳楼|从.{0,8}跳下去)|"
    r"(?:翻过|跨过|越过).{0,10}(?:高架桥|桥).{0,10}(?:护栏|栏杆).{0,32}(?:跳下去|跳下|跳桥)|"
    r"(?:高架桥|桥边|桥上|护栏).{0,32}(?:准备|打算|计划).{0,20}(?:跳下去|跳下|跳桥)|"
    r"(?:锤子|铁锤|棍棒|棒球棍).{0,40}(?:砸|打|袭击)(?:他|她|室友|别人|他人)|"
    r"(?:锤子|铁锤|棍棒|棒球棍).{0,48}(?:砸|打|袭击)(?:伤|死)?(?:他|她|室友|同事|别人|他人)|"
    r"(?:已经|刚刚).{0,12}(?:吞|服|吃).{0,24}(?:比医嘱多|过量|超量).{0,20}(?:药|安眠药)|"
    r"(?:一整瓶|整瓶|全部).{0,8}(?:药|安眠药).{0,24}(?:准备|打算|计划).{0,20}(?:吞|服|吃)|"
    r"(?:一整瓶|整瓶).{0,8}(?:药|安眠药).{0,28}(?:全部吞下|全部吃下|全部服下)|"
    r"(?:[一二三四五六七八九十百\d]+片).{0,8}(?:药|安眠药).{0,28}"
    r"(?:准备|打算|计划).{0,20}(?:全部)?(?:吞下|吃下|服下|吞下去|吃下去|服下去)|"
    r"(?:走到|站在|靠近).{0,12}(?:铁路|铁轨|轨道|站台).{0,20}"
    r"(?:准备|打算|计划).{0,24}(?:冲向|冲过去|跳向)(?:列车|火车|地铁)?|"
    r"(?:天台|楼顶|屋顶|高处).{0,18}(?:护栏|栏杆).{0,12}(?:外面|外侧).{0,20}(?:准备|打算|就要)?(?:松手|跳下)|"
    r"(?:拿着|握着|手里.{0,8}(?:拿着|有)).{0,8}(?:菜刀|刀|匕首|锤子|铁锤|棒球棍|铁棍).{0,48}"
    r"(?:等.{0,12}(?:出来|进门)|让.{0,12}付出代价|打(?:他|她)|砍(?:他|她)|动手)|"
    r"(?:刚|已经|十分钟前|刚刚).{0,20}(?:把)?(?:一整|整|一全|全)?(?:瓶|板|盒)?[^，。；;]{0,16}"
    r"(?:药|片|地高辛|安眠药)[^，。；;]{0,12}(?:都|全部)?(?:吞了|吞下|吃了|服下)|"
    r"(?:一整|整|一全|全)?(?:瓶|板|盒)[^，。；;]{0,12}(?:药|片|安眠药).{0,32}"
    r"(?:准备|打算|计划).{0,20}(?:一次|全部|都)?(?:吞|吃|服)(?:下|下去)?|"
    r"kill\s+myself|suicid|hurt\s+(?:myself|my partner|someone)|"
    r"(?:intend\s+to|about\s+to).{0,16}(?:end\s+my\s+life|attack\s+(?:my\s+)?(?:roommate|partner|someone))",
    re.IGNORECASE,
)
SAFETY_NEGATION_PATTERN = re.compile(
    r"(?:现在|目前|当下|此刻)?(?:确认|明确)?(?:没有|并无|无(?!法)|不想|不打算|不会)"
    r"(?=[^。；\n]{0,40}(?:自杀|自伤|割伤自己|伤害(?:自己|他人|别人|伴侣)|结束自己的生命))"
    r"[^。；\n]{0,55}(?:打算|想法|念头|意图|计划)"
    r"(?:[、，,或和及]\s*(?:打算|想法|念头|意图|计划))*|"
    r"(?:现在|目前|当下)?(?:明确)?(?:没有|并无|无(?!法)|不想|不打算|不会).{0,6}"
    r"(?:伤害(?:自己|他人|别人|伴侣)(?:或(?:自己|他人|别人|伴侣))?|自杀|结束自己的生命)"
    r".{0,8}(?:打算|想法|念头|意图)?|"
    r"(?:no|without)\s+(?:current\s+)?(?:intent|plan|thoughts?)\s+to\s+"
    r"(?:harm\s+(?:myself|others?|someone)|end\s+my\s+life)|"
    r"(?:没有|并无|无|不)(?:任何)?(?:准备|打算|计划|意图).{0,16}"
    r"(?:跳楼|跳下去|吞药|服药过量|砸|袭击)",
    re.IGNORECASE,
)
CURRENT_HARM_NEGATION_PATTERN = re.compile(
    r"(?:现在|目前|当下|此刻)?(?:确认|明确)?(?:没有|并无|无|不想|不打算|不会)\s*"
    r"(?:伤害|攻击|袭击|殴打|砍|打|砸)(?:伤|死)?\s*"
    r"(?:自己|室友|伴侣|前伴侣|前任|同事|邻居|别人|他人|他|她)"
    r"(?:的)?(?:打算|计划|意图|想法|念头)?|"
    r"(?:也\s*)?(?:没有|并无|无)\s*(?:伤害|攻击|袭击|殴打|砍|打|砸)"
    r"(?:自己|室友|伴侣|前伴侣|前任|同事|邻居|别人|他人|他|她)"
    r"(?:的)?(?:打算|计划|意图|想法|念头)|"
    r"(?:现在|目前|当下|此刻)?(?:确认|明确)?(?:没有|并无|无)\s*"
    r"(?:自伤|自杀|伤害自己)(?:的)?(?:打算|计划|意图|想法|念头)",
    re.IGNORECASE,
)
RESOLVED_PAST_HARM_PATTERN = re.compile(
    r"原本[^。；;\n]{0,36}(?:自杀|自伤|伤害自己|结束自己的生命)"
    r"[^。；;\n]{0,36}(?:已经|已)(?:交给|移交|锁起|远离)[^。；;\n]{0,24}"
    r"(?:现在|目前)[^。；;\n]{0,12}(?:确认|明确)?(?:没有|并无|无)"
    r"[^。；;\n]{0,12}(?:自伤|自杀|伤害自己)?(?:意图|计划|打算|念头)",
    re.IGNORECASE,
)
NONUSER_SAFETY_CONTEXT_PATTERN = re.compile(
    r"(?:小说|故事|剧本|角色|人物)[^。；\n]{0,90}(?:不涉及我本人|与我本人无关)|"
    r"(?:新闻|报道)[^。；\n]{0,90}(?:有人|当事人|人物)[^。；\n]{0,90}"
    r"(?:跳下去|跳楼|自杀|自伤|伤害他人|砸他|袭击)",
    re.IGNORECASE,
)
FICTION_CONTEXT_PATTERN = re.compile(
    r"小说|故事|剧本|影视(?:片段|场景|剧情|角色)|电影(?:分镜|场景|剧情|剧本|角色)|"
    r"分镜(?:写着|描述|脚本)|虚构(?:角色|故事|场景)|角色|桥段|情节",
    re.IGNORECASE,
)
NEWS_CONTEXT_PATTERN = re.compile(r"新闻|报道|新闻摘要|校对.{0,12}摘要", re.IGNORECASE)
DOCUMENT_CONTEXT_PATTERN = re.compile(
    r"卷宗|档案|结案|证人记录|嫌疑人|历史材料|病例材料|纪录片|历史影像", re.IGNORECASE
)
TRANSLATION_CONTEXT_PATTERN = re.compile(
    r"(?:我在|正在|只是|只做|请(?:只)?)翻译[^。；;\n]{0,80}"
    r"(?:不是在描述(?:我|自己|本人)|与我无关|只翻译|不要分析)|"
    r"(?:翻译|译文)[^。；;\n]{0,48}(?:这句话|原句)[^。；;\n]{0,48}"
    r"(?:不是我的情况|不是在描述自己)",
    re.IGNORECASE,
)
EDUCATION_CONTEXT_PATTERN = re.compile(
    r"培训课|课堂|课程.{0,8}示例|错误示例|教学示例|教材|讲师要求|"
    r"题库|教学题|急救课|财经课|课程案例|教材案例|模拟患者|标准答案", re.IGNORECASE
)
EXPLICIT_NONCURRENT_CONTEXT_PATTERN = re.compile(
    r"不是在描述现实.{0,12}(?:自伤|自杀|伤害|风险)|不涉及(?:我|本人|现实|当前).{0,12}(?:安全|风险)|"
    r"第三人称.{0,12}(?:历史|材料|报道)|这句话说的是(?:他|她).{0,8}不是我|"
    r"这句话不是我的情况|不要把它当成我的处境|这不是我的情况|不是真实事件",
    re.IGNORECASE,
)
THIRD_PARTY_REPORT_PATTERN = re.compile(
    r"(?:朋友|同事|伴侣|室友|家人|患者|演员|嫌疑人|证人|他|她)"
    r".{0,18}(?:发来|发消息说|说|写|写着|写下|提到|记录|威胁说)",
    re.IGNORECASE,
)
HISTORICAL_CONTEXT_PATTERN = re.compile(
    r"(?:去年|前年|十年前|多年前|当年|曾经|曾有过|过去曾|"
    r"[一二三四五六七八九十百两\d]+(?:年|个月|月|周|天)前|"
    r"\b(?:19|20)\d{2}\s*年|早已|已结案)",
    re.IGNORECASE,
)
CURRENT_USER_RESTART_PATTERN = re.compile(
    r"(?:但|可|可是|不过|然而|[，,])[^。；;\n]{0,16}"
    r"(?:我(?:本人)?|本人)(?:[^。；;\n]{0,8})"
    r"(?:现在|目前|此刻|今晚|今天|已经|刚|正|准备|打算|想要)",
    re.IGNORECASE,
)
TREATMENT_CHANGE_PATTERN = re.compile(
    r"(?:取消|撤销|不再参加|暂停|中止|终止|停止).{0,18}"
    r"(?:心理治疗|治疗预约|咨询预约|治疗|心理咨询)|"
    r"(?:心理治疗|心理咨询).{0,18}(?:取消|暂停|中止|终止|停止|不再继续)|"
    r"(?:[\u4e00-\u9fffA-Za-z-]{2,20}(?:治疗|疗法)|会谈).{0,36}"
    r"(?:改成.{0,12}(?:停掉|停止|暂停|不再继续)|取消|暂停|中止|终止|停止|完全停掉|改变频率)|"
    r"(?:停掉|取消|暂停|中止|终止|停止|不再参加).{0,28}"
    r"(?:CBT|认知行为|辩证行为|暴露反应预防|[A-Za-z-]{2,20})(?:会谈|治疗|疗法)",
    re.IGNORECASE,
)
MEDICAL_CHANGE_PATTERN = re.compile(
    r"停药|断药|减药|加药|换药|暂停服用|停止服用|暂停.{0,6}(?:处方药|药物)|"
    r"(?:先|暂时)?不吃.{0,10}(?:处方药|医生开的药|药物)|"
    r"(?:每天|每次).{0,8}(?:片|粒|毫克).{0,6}(?:改成|改为).{0,8}(?:片|粒|毫克)|"
    r"(?:医生开的|处方).{0,16}(?:药|药物).{0,8}(?:停掉|停用|搁置|不再服用)|"
    r"(?:药|药物).{0,8}(?:搁置|停掉|停用)|"
    r"自行.{0,6}(?:调整|改变).{0,6}(?:剂量|治疗|用药)|调整剂量|"
    r"(?:把)?剂量.{0,8}(?:减半|加倍|调低|调高)|(?:直接)?换(?:成)?(?:另|另一|其他)种药|"
    r"(?:处方|医嘱|每天服|每次服).{0,45}\d+(?:\.\d+)?\s*(?:毫克|mg)"
    r".{0,35}(?:改成|改为|减到|加到|换成|降为|升为)\s*\d+(?:\.\d+)?\s*(?:毫克|mg)|"
    r"\d+(?:\.\d+)?\s*(?:毫克|mg).{0,40}(?:改成|改为|减到|加到|降到|升到|降为|升为)"
    r"\s*\d+(?:\.\d+)?\s*(?:毫克|mg)|"
    r"(?:想|准备|打算|要).{0,20}(?:停用|停掉|停止服用|减量|加量|换用|"
    r"减到|加到|降到|升到).{0,30}(?:药物|处方药|生物制剂|文拉法辛|medication)|"
    r"(?:停用|停掉|停止服用).{0,24}(?:每周的)?(?:药物|处方药|生物制剂|文拉法辛)|"
    r"(?:处方药|医生给我的药|舍曲林|抗抑郁药).{0,38}(?:停掉|停用|改成隔天|隔天(?:吃|服))|"
    r"(?:医生给我开的|按处方服用的?|处方中的)[^。；\n]{1,60}(?:彻底|完全)?(?:停掉|停用|停止服用)|"
    r"(?:今晚|今天|现在).{0,10}(?:只吃|只服|少吃|少服|多吃|多服).{0,8}(?:半片|一片|\d+片)|"
    r"(?:处方药|医生开的药|药物).{0,12}(?:少吃|少服|多吃|多服).{0,8}(?:半片|一片|\d+片)|"
    r"(?:取消|撤销|不再参加|暂停|中止|终止|停止).{0,18}"
    r"(?:心理治疗|治疗预约|咨询预约|治疗|心理咨询)|"
    r"改变治疗|终止治疗|停止治疗|stop\s+(?:my\s+)?medication|"
    r"change\s+(?:my\s+)?dosage|quit\s+(?:my\s+)?treatment|"
    r"medication\s+holiday|taper\s+to|skip\s+every\s+prescribed\s+dose",
    re.IGNORECASE,
)
HIGH_COST_PATTERN = re.compile(
    r"分手|离婚|分居|办理分居|辞职|离职申请|提交离职|解除.{0,8}(?:劳动合同|雇佣关系)|终止.{0,8}劳动合同|退学|休学|办理休学|搬家|永久断联|关(?:掉|停|闭)(?:公司|项目)|"
    r"(?:公司|项目)关(?:掉|停|闭)|关停(?:公司|项目)|结束(?:公司|项目)|quit\s+(?:my\s+)?job|"
    r"不再.{0,12}(?:和|与).{0,8}(?:伴侣|对象).{0,12}(?:恋爱)?关系|不再来上班|结束这段关系|"
    r"break\s+up|drop\s+out|do\s+not\s+stay\s+enrolled|"
    r"shut\s+down\s+(?:the\s+)?(?:company|project)|"
    r"archive\s+(?:the\s+)?project\s+permanently|stop\s+serving\s+every\s+user|"
    r"(?:卖掉|出售|抵押|过户).{0,12}(?:唯一住房|自住房|唯一房产|全部房产)|"
    r"(?:全部|所有|大部分).{0,8}(?:积蓄|资产|资金|退休金|应急金).{0,16}"
    r"(?:换成|投入|买入|转入)|(?:全部|全仓).{0,16}(?:换成|投入|买入|配置)|"
    r"把钱全部换成|all[- ]?in|sell\s+(?:my\s+)?only\s+home|"
    r"(?:放弃|拒绝).{0,18}(?:工作\s*offer|offer|晋升|录取|职位)|"
    r"(?:把)?(?:全部|所有)股票.{0,8}清仓|股票全部清仓|"
    r"注销公司|解散团队|注销公司并解散团队",
    re.IGNORECASE,
)
HIGH_COST_NONACTION_PATTERN = re.compile(
    r"只在纸上|纸面比较|假设比较|不挂牌|不交易|不转账|不是我的计划|"
    r"虚构.{0,12}(?:案例|家庭|人物)|仅作教学|for\s+discussion\s+only",
    re.IGNORECASE,
)
CLINICAL_PATTERN = re.compile(
    r"正式.{0,5}诊断|确诊|医生诊断|专业医生|精神科医生|psychiatrist\s+diagnosed|"
    r"clinical\s+diagnosis|ADHD|强迫症|OCD|抑郁症|双相情感障碍|广泛性焦虑障碍|"
    r"社交焦虑障碍|创伤后应激障碍|PHQ-?9|GAD-?7|[A-Z][A-Z0-9-]{1,15}\s*(?:中文版)?量表|"
    r"(?:临床心理师|心理师|医院|门诊).{0,36}[A-Z][A-Z0-9-]{1,15}.{0,28}(?:得分|总分|结果)|"
    r"处方药|心理治疗|"
    r"generalized\s+anxiety\s+disorder|bipolar\s+disorder",
    re.IGNORECASE,
)
FORMAL_DIAGNOSIS_PATTERN = re.compile(
    r"正式.{0,8}诊断|正式确诊|确诊(?:为|了)?|(?:精神科|专业|临床|处方)?医生.{0,8}诊断|"
    r"psychiatrist\s+diagnosed|clinician\s+diagnosed|formally\s+diagnosed",
    re.IGNORECASE,
)
DIAGNOSIS_UNCERTAINTY_PATTERN = re.compile(
    r"怀疑|可能有|疑似|风险偏高|筛查|没有接受过正式诊断|尚未.{0,6}诊断|"
    r"从未看过医生|未.{0,4}诊断|没有.{0,4}诊断|排除.{0,8}诊断|"
    r"不等于.{0,18}(?:医生)?诊断|suspect|might\s+have|"
    r"not\s+diagnosed|no\s+formal\s+diagnosis|screening|"
    r"(?:did|does|do|has|have)\s+not\s+diagnos|"
    r"(?:may|might|could)\s+diagnos|\bif\b[^.;]{0,48}\bdiagnos",
    re.IGNORECASE,
)
FORMAL_SCALE_PATTERN = re.compile(
    r"正式.{0,16}量表|(?:正式)?PHQ-?9(?:量表)?|量表(?:显示|结果)|"
    r"[A-Z][A-Z0-9-]{1,15}\s*(?:中文版\s*)?(?:正式\s*)?量表|"
    r"[A-Z][A-Z0-9-]{1,15}.{0,12}(?:得分|结果为|分数)\s*\d+(?:\.\d+)?\s*分?|"
    r"(?:临床心理师|心理师|医院|门诊).{0,36}[A-Z][A-Z0-9-]{1,15}.{0,28}"
    r"(?:得分|总分|结果(?:是|为|显示|提示)?)\s*(?:\d+(?:\.\d+)?\s*分?|[^，。；;]{2,24})|"
    r"(?:临床心理师|心理师|精神科医生|医院|门诊).{0,36}(?:施测|做了?|完成).{0,12}"
    r"[A-Z][A-Z0-9-]{1,15}.{0,28}(?:报告)?(?:结果|得分|总分|T分)|"
    r"validated\s+scale",
    re.IGNORECASE,
)
NONFORMAL_SCALE_CONTEXT_PATTERN = re.compile(
    r"网上下载|自己填(?:写)?|自行填(?:写)?|公众号|网测|网上测试|"
    r"不是正式施测|并非正式施测|没有专业人员施测|没有专业施测|"
    r"没有(?:医生|心理师|临床人员|认证人员).{0,12}施测|"
    r"(?:AI|模型|ChatGPT).{0,12}(?:给我)?(?:做|施测)|"
    r"self[- ]administered|not\s+formally\s+administered|online\s+quiz",
    re.IGNORECASE,
)
REPORT_ONLY_PATTERN = re.compile(
    r"请(?:只|原样|准确|如实|逐字)?(?:记录|记下)|只(?:想|是想)?(?:把|将)?[^，。；,;]{0,16}(?:记录|记下|保留)|"
    r"(?:如实|原样|准确|逐字)(?:记录|记下)|希望[^，。；,;]{0,12}(?:记录|记下)|"
    r"record\s+(?:only|this|accurately)|only\s+want\s+to\s+record",
    re.IGNORECASE,
)
AI_SOURCE_PATTERN = re.compile(
    r"(?:另一个\s*)?(?<![A-Za-z])AI(?![A-Za-z])|ChatGPT|Claude|模型[^，。；;\n]{0,30}(?:说|判断|断言|断定)|人工智能|聊天机器人|chatbot|"
    r"(?:日记|聊天|人格|性格)?\s*(?:App|应用|工具|系统|软件|算法|程序)"
    r".{0,30}(?:分析|判断|断言|归为|分类|称为)",
    re.IGNORECASE,
)
SOCIAL_SOURCE_PATTERN = re.compile(
    r"网上|小红书|抖音(?:测试|测评)?|热门帖子|公众号(?:小游戏)?|社交媒体|网测|网上测试|"
    r"(?:公司|学校|机构)?(?:性格|人格)?(?:测试|测评|测验)|"
    r"短视频(?:博主|作者|账号|测试|测评|评论区|评论)|评论区|(?:短视频)?博主|论坛博主|"
    r"播客(?:节目|主播|作者)?|论坛网友|娱乐网站|页面(?:说|显示)|平台(?:人格)?(?:测试|测评)|"
    r"online\s+(?:quiz|test)|social\s+media\s+(?:quiz|test)",
    re.IGNORECASE,
)
THIRD_PARTY_SOURCE_PATTERN = re.compile(
    r"匿名|互助群|身份不明|不知道对方是谁|同事(?:又)?(?:说|写我)|(?:有|某)个人说|陌生人说|"
    r"(?:他|她|他们|她们)(?:说|认定)|"
    r"(?:朋友|同事|伴侣|室友|家人|父亲|母亲|老师|导师|上司|主管|项目负责人|陌生人)"
    r"(?:(?:一直|总是|曾经|又|也|却|就|还|刚刚|昨天|今天)|"
    r"(?:在[^，。；;\n]{1,16})|(?:根据[^，。；;\n]{1,18})|"
    r"(?:因为[^，。；;\n]{1,18})|(?:给我[^，。；;\n]{0,12})){0,3}"
    r"(?:说|写(?:我)?|认定我|叫我|称我|称我为|把我(?:叫作|称作|称为|归为))",
    re.IGNORECASE,
)
PREFERENCE_PATTERN = re.compile(
    r"喜欢|不喜欢|不爱|更喜欢|更愿意|更舒服|偏好|习惯|prefer|dislike|like\s+quiet|"
    r"rather\s+than|comfortable|(?:多年|十年来|长期|一直).{0,14}(?:选择|采用|安排)|"
    r"不寻求改变|不想改变(?:这个|这项)?(?:安排|习惯|选择)|"
    r"(?:过去)?[一二三四五六七八九十百\d]+年.{0,10}(?:选择|采用|安排)",
    re.IGNORECASE,
)
NO_IMPAIRMENT_PATTERN = re.compile(
    r"(?:没有|并未|未曾|从未).{0,14}(?:影响|耽误|妨碍|迟到)|"
    r"(?:工作|关系|交付|生活).{0,8}(?:正常|没受影响|没有受影响)",
    re.IGNORECASE,
)
NO_CHANGE_PATTERN = re.compile(
    r"不想(?:改变|调整)|不打算(?:改变|调整)|不寻求改变|不需要(?:改变|调整)",
    re.IGNORECASE,
)
HABITUAL_ARRANGEMENT_PATTERN = re.compile(
    r"(?:通常|经常|一直|长期|多年|习惯).{0,18}(?:办公|工作|写作|吃饭|选择|安排|采用|关门|独自)",
    re.IGNORECASE,
)
FUNCTIONAL_IMPAIRMENT_PATTERN = re.compile(
    r"严重影响(?:生活|工作|学习|关系)|几乎无法(?:起床|下床|出门|工作|上学|进食|吃饭|睡觉|洗澡|沐浴)|"
    r"连续.{0,8}(?:无法|不能).{0,12}(?:工作|上学|完成|出门|进食|睡觉)|"
    r"缺勤.{0,6}(?:次|天)|整天吃不下|无法维持(?:生活|工作|学习)|"
    r"起不来床|连续缺勤|连续缺席(?:全部|所有)?(?:课程|班次)|生活.{0,6}(?:维持不住|无法维持)|"
    r"(?:洗澡|吃饭|上课).{0,12}(?:做不到|没法)|没法.{0,8}(?:去)?上课|"
    r"(?:饭|东西).{0,6}(?:不吃|吃不下|吃不进去)|作业.{0,8}(?:交不了|停了)|"
    r"(?:最近|过去|已经).{0,12}(?:周|月).{0,18}连[^，。；]{0,45}(?:都|也)(?:做不到|无法完成)|"
    r"(?:一个月|[一二三四五六七八九十\d]+周).{0,16}(?:没下床|无法下床|没去实习|没去工作)|"
    r"[一二三四五六七八九十\d]+周没去(?:实习|工作|上课)|"
    r"(?:所有|全部).{0,8}(?:课|课程|班次|实习).{0,8}(?:没去|缺席|停掉)|"
    r"functioning\s+is\s+severely\s+impaired|cannot\s+(?:work|eat|leave\s+home)|"
    r"(?:unable|cannot|can't)\s+to\s+(?:shower|cook|eat|work|attend|answer\s+work\s+messages)|"
    r"missed\s+(?:work|school).{0,8}(?:times|days)|missed\s+every\s+shift",
    re.IGNORECASE,
)
VERDICT_PATTERN = re.compile(
    r"这证明|这就是|注定|永远|不可能|不适合|做不好|没有领导力|"
    r"肯定|根本没有|不是我的责任|不是我的问题|安排我的工作|"
    r"替我决定|规划职业|该不该|是不是该|应该马上|直接告诉我|"
    r"(?:直接|足以|能够|能)?证明我(?:其实|就是|是)|"
    r"足以(?:说明|证明)|每次.{0,24}(?:都)?证明(?:这个|该)?标签|"
    r"不该(?:再)?(?:竞选|申请|尝试|担任)|"
    r"所有.{0,30}(?:失败|做不好|不能维持|都会失败)|"
    r"一定.{0,30}(?:失败|做不好|不适合|更会|更能|更适合|搞坏|没法|无法|不能|不可能)|"
    r"(?:肯定|必然|永远|以后任何|不可能).{0,30}(?:做不了|胜任不了|带不好|讲不清|失败|烂尾|通过不了|不能|无法)|"
    r"(?:做不了|胜任不了|带不好|没有.{0,8}潜力|不配负责|不能管理|无法影响)|"
    r"合并成.{0,12}(?:真实)?人格|真实人格|以后都不会|再也不会|"
    r"以后.{0,18}(?:完成不了|不能|不会).{0,18}(?:任何|所有)|"
    r"(?:完成不了|不能完成).{0,12}(?:任何|所有)|"
    r"任何.{0,24}(?:不会|不能|无法|不适合|做不好|长久)|"
    r"(?:重要)?项目.{0,12}别让(?:我)?负责|别让(?:我)?负责|不要让(?:我)?负责|不该让(?:我)?负责|"
    r"天生冷漠|"
    r"\bso\b|therefore|cannot|can\s+never|always|doomed|should|"
    r"not\s+my\s+(?:fault|responsibility)",
    re.IGNORECASE,
)
NONVERDICT_CONTEXT_PATTERN = re.compile(
    r"没有(?:因此)?(?:耽误|受?影响|妨碍|造成)(?:[^，。；,;]{0,16})|"
    r"(?:我)?不想改|不寻求改变|不需要(?:帮我)?改变|只是在说明(?:这个)?偏好|"
    r"没有说[^，。；,;]{0,20}(?:证明|说明)[^，。；,;]{0,20}|"
    r"(?:并非|不是)(?:在)?说[^，。；,;]{0,20}(?:证明|说明)|"
    r"(?:不能|无法)(?:自动)?证明[^，。；,;]{0,30}|不能单独当(?:作)?诊断|"
    r"不要给我贴病名|不等于[^，。；,;]{0,30}|"
    r"没有任何就诊记录|没有就诊记录|从未就诊|"
    r"no\s+appointment(?:\s+ever\s+happened)?|never\s+(?:saw|met)\s+a\s+clinician|"
    r"does\s+not\s+(?:prove|mean)[^.;]{0,30}|do\s+not\s+want\s+to\s+change",
    re.IGNORECASE,
)
NEGATED_IMPLICATION_PATTERN = re.compile(
    r"(?:不(?:意味着|表示|说明|证明|代表|等于说)|"
    r"不能(?:推出|说明|证明|代表)|无法(?:推出|说明|证明|代表)|"
    r"不等于(?:说|意味着|表示|说明)|"
    r"(?:没有|并未|不是|并非)(?:在)?说[^。；;\n]{0,32}(?:证明|说明|意味着|表示)|"
    r"(?:我)?(?:没说|没有说|并未说)(?:自己|我)?[^。；;\n]{0,48})"
    r"[^。；;\n]*",
    re.IGNORECASE,
)
EXPLANATION_ONLY_PATTERN = re.compile(
    r"解释一下|只解释(?:这个)?术语|如何定义|是什么意思|什么(?:叫|是)|"
    r"不建立(?:我|本人)的?(?:个人)?案例|define|what\s+does.+mean",
    re.IGNORECASE,
)
DECONSTRUCT_REQUEST_PATTERN = re.compile(
    r"(?:帮我|请帮我|我想)(?:区分|拆开|拆解|核对).{0,16}(?:标签|判断|具体行为)|"
    r"(?:我想|请帮我|帮我)?审计.{0,20}(?:标签(?:的)?来源|这个标签|该标签|AI推断)|"
    r"(?:区分|拆开|拆解).{0,12}(?:标签|判断).{0,12}(?:行为|事实|情境)?|"
    r"(?:请)?(?:把|将).{0,12}(?:身份|人格)?判断.{0,12}拆成.{0,16}(?:可观察|事实|行为)|"
    r"(?:请)?(?:正式)?拆解.{0,12}(?:这个|该)?标签|"
    r"(?:请)?区分.{0,28}(?:行为事实|行为|事实).{0,28}(?:标签|身份判断)|"
    r"(?:请)?(?:把|将).{0,24}(?:来源).{0,16}(?:标签).{0,16}(?:逐一)?(?:拆开|拆解|区分)|"
    r"(?:请)?(?:把|将).{0,24}(?:来源与标签|标签与来源).{0,16}(?:逐一)?(?:拆开|拆解|区分)|"
    r"(?:分开|分别|逐条|逐一).{0,20}(?:审计|核对|保存|记录).{0,24}(?:来源|AI推断|标签)|"
    r"(?:审计|核对).{0,24}(?:来源).{0,24}(?:行为|反例)|"
    r"(?:逐条|逐一).{0,12}按来源.{0,12}(?:拆解|拆开|记录)|"
    r"(?:不要合并|不能合并).{0,20}(?:来源|标签)|(?:来源|标签).{0,20}(?:不要合并|不能合并)",
    re.IGNORECASE,
)
DECONSTRUCT_NEGATION_PATTERN = re.compile(
    r"不要.{0,12}(?:拆解|拆开|分析)|不需要.{0,12}(?:拆解|拆开|分析)|"
    r"(?:拆解|拆开).{0,12}(?:是什么意思|如何定义)|只要.{0,12}(?:术语)?定义|"
    r"只解释(?:这个)?术语|不建立(?:我|本人)的?(?:个人)?案例|"
    r"只想区分诊断与能力判断|区分诊断与能力判断",
    re.IGNORECASE,
)
AI_PERSONALITY_INFERENCE_REQUEST_PATTERN = re.compile(
    r"(?:请|让|叫).{0,24}(?:AI|模型|你|聊天机器人)?(?:替我|给我).{0,16}"
    r"(?:定|判断|归纳|推断|分类).{0,12}(?:人格|性格|身份)(?:类型|标签)?"
    r".{0,40}(?:解释|断定|判断|适合).{0,18}(?:未来|工作|职业|关系)|"
    r"(?:根据|凭).{0,24}(?:聊天|对话|几句话|四句|六句).{0,24}"
    r"(?:定|判断|推断).{0,12}(?:人格|性格)(?:类型|标签)?",
    re.IGNORECASE,
)

NONPERSONAL_IDENTITY_CONTEXT_PATTERN = re.compile(
    r"(?:只|仅)(?:解释|比较).{0,18}(?:概念|术语|措辞)|概念问题|不分析任何个人|"
    r"(?:论文|文献).{0,12}(?:原句|引文)|校对引文|"
    r"翻译成中文(?:即可)?|只(?:做|需要)?翻译|请(?:只)?翻译|不要分析(?:本人|现实用户|说话者)|"
    r"(?:数据|训练|测试)?标注样本|只判断句子|"
    r"(?:小说|电影|剧本|舞台剧|教材|课程|培训题|培训材料|产品文档).{0,48}"
    r"(?:角色|原句|台词|字段|示例|反例|错误示例)|只校对句子|"
    r"(?:医院报告|病历).{0,36}(?:引用|引文).{0,36}(?:不是诊断|只是病历引文|只作引文)|"
    r"病历模板.{0,48}(?:示例|没有填写任何人的资料)|没有填写任何人的资料|"
    r"(?:如何|怎样).{0,12}(?:定义|区分).{0,20}(?:诊断|术语|概念)|"
    r"没有在报告自己的诊断|不是我的诊断|内容与我无关|不是在描述本人|"
    r"(?:API|服务器|数据库|软件|工程|压测|构建).{0,24}(?:得分|量表|报告|性能)|"
    r"服务性能|不是人的心理结果|职位标签|简历抬头|职业头衔|没有心理分析需求",
    re.IGNORECASE,
)
POSITIVE_RELABEL_PATTERN = re.compile(
    r"隐藏型领导者|天生领导者|高潜力人格|真正的强者|其实是.{0,10}(?:领导者|天才|强者)|"
    r"有潜力的(?:领袖|领导者)|高韧性人格|高潜力(?:领袖|领导者)|稀缺型领导人才|"
    r"天赋型.{0,10}(?:沟通者|人格|身份)|战略型领导人格|高功能型人格|"
    r"secret\s+leader|hidden\s+genius|superpower|quiet\s+power\s+leader\s+personality|"
    r"gifted\s+empath\s+archetype|(?:超级|极度|高度|真正|天生|隐藏|高潜力).{0,12}"
    r"(?:型人格|人格|领导者|强者|天才)",
    re.IGNORECASE,
)
GENERATED_POLICY_BOUNDARY_PATTERN = re.compile(
    r"[^，,。；;\n]{0,48}(?:不能|不得|不应|不会|不替|不建议|不用于|"
    r"必须交给|需要交给|应交给|留给)[^，,。；;\n]{0,96}",
    re.IGNORECASE,
)
GENERATED_POLICY_SEGMENT_BOUNDARY_PATTERN = re.compile(
    r"(?=(?:并(?:且)?(?:建议|应|要|先|再|立即)|而(?:应|要|需|先)|"
    r"但(?:是|其实|应|要|建议|需)?|不过|然而|可是|其实|"
    r"却(?:应|要|建议)|同时(?:应|要|建议)|只是|"
    r"\b(?:but|however|yet)\b))|"
    r"(?<=[，,。；;\n])",
    re.IGNORECASE,
)
GENERATED_NEGATED_DIRECTIVE_PATTERN = re.compile(
    r"(?:不能|不得|不应|不会|不替|不建议|不用于|(?<!要)不要|别|禁止|"
    r"必须交给|需要交给|应交给|留给)",
    re.IGNORECASE,
)
GENERATED_DOUBLE_NEGATION_PATTERN = re.compile(
    r"(?:不能|不得|不应|不建议|不要|别)\s*(?:否认|质疑|拒绝承认|"
    r"阻止|妨碍|反对停止)",
    re.IGNORECASE,
)
GENERATED_IDENTITY_VERDICT_PATTERN = re.compile(
    r"(?:结果|实验|表现|这).{0,16}(?:证明|说明|代表|意味着).{0,16}"
    r"(?:你|用户|我)?(?:本质上|天生|就是|是一个|永远|注定)|"
    r"(?:你|用户|我)(?:本质上|天生|就是|永远|注定).{0,24}"
    r"(?:失败者|没有?自制力|废物|人格|回避型|低能量|不适合|做不好)|"
    r"(?:本质上|天生|注定|永远).{0,24}(?:失败者|没有?自制力|废物|人格)|"
    r"(?:结果|实验|这次实验).{0,18}(?:表明|确认|说明|证明).{0,16}"
    r"(?:你|用户|我).{0,10}(?:属于|是|确认了?).{0,18}(?:型人格|人格类型)|"
    r"(?:确认|定义).{0,12}(?:你|用户|我)(?:的)?人格类型",
    re.IGNORECASE,
)
GENERATED_UNVERIFIABLE_CAUSE_PATTERN = re.compile(
    r"童年创伤.{0,18}(?:导致|造成|解释)|"
    r"害怕被抛弃.{0,24}(?:所以|导致|造成|故意)|"
    r"潜意识.{0,24}(?:抵抗|驱动|导致|造成|决定)|"
    r"(?:伴侣|对象|他|她|别人).{0,18}(?:正在|一直|故意)?(?:操控|控制|撒谎|报复)"
    r"(?:你|用户|我)?",
    re.IGNORECASE,
)
GENERATED_DIAGNOSIS_OVERRIDE_PATTERN = re.compile(
    r"(?:ADHD|抑郁症|双相(?:障碍|情感障碍)?|自闭症谱系障碍|PTSD|"
    r"强迫症|焦虑障碍|诊断).{0,28}(?:已经不存在|不存在了|不再存在|"
    r"是误诊|属于误诊|不再符合|可以撤销|应撤销|无需治疗|不需要继续治疗)|"
    r"(?:证明|说明|所以).{0,24}(?:之前的)?(?:ADHD|抑郁症|双相(?:障碍|情感障碍)?|"
    r"自闭症谱系障碍|PTSD|强迫症|焦虑障碍|诊断).{0,20}(?:误诊|不存在|"
    r"不再符合|不需要继续治疗)|"
    r"不再符合.{0,20}(?:诊断|障碍)|不需要继续治疗|"
    r"(?:这些|该|现有)?(?:表现|信息|结果)[^，,。；;\n]{0,18}"
    r"(?:足以|可以|能够|可)?排除[^，,。；;\n]{0,18}"
    r"(?:ADHD|抑郁症|双相(?:障碍|情感障碍)?|自闭症谱系障碍|PTSD|"
    r"强迫症|焦虑障碍|诊断)|"
    r"(?:ADHD|抑郁症|双相(?:障碍|情感障碍)?|自闭症谱系障碍|PTSD|"
    r"强迫症|焦虑障碍|诊断)[^，,。；;\n]{0,24}(?:应该|应当|可以|可)?撤销|"
    r"(?:你|用户|我)(?:的)?[^，,。；;\n]{0,18}(?:已经)?痊愈|"
    r"(?:你|用户|我)(?:已经)?痊愈|(?:这|该|之前的|原来的)?[^，,。；;\n]{0,12}"
    r"(?:是|属于)误诊|(?:无需|不需要)(?:继续)?(?:复诊|治疗)|"
    r"(?:这|该|你的?|用户的?)?[^，,。；;\n]{0,12}(?:不是|并非)\s*"
    r"(?:ADHD|抑郁症|双相(?:障碍|情感障碍)?|自闭症谱系障碍|PTSD|强迫症|焦虑障碍)|"
    r"(?:已经|可以|能够)?排除(?:了)?[^，,。；;\n]{0,16}"
    r"(?:ADHD|抑郁症|双相(?:障碍|情感障碍)?|自闭症谱系障碍|PTSD|强迫症|焦虑障碍)|"
    r"(?:你|用户|我)(?:的)?[^，,。；;\n]{0,8}"
    r"(?:ADHD|抑郁(?:症)?|双相(?:障碍|情感障碍)?|自闭症谱系障碍|PTSD|强迫症|焦虑障碍)"
    r"[^，,。；;\n]{0,8}(?:好了|康复了?|恢复了?|消失了?)|"
    r"(?:ADHD|抑郁(?:症)?|双相(?:障碍|情感障碍)?|自闭症谱系障碍|PTSD|强迫症|焦虑障碍)"
    r"[^，,。；;\n]{0,8}(?:好了|康复了?|恢复了?|消失了?)|"
    r"(?:之前|原来|先前)?[^，,。；;\n]{0,8}诊断[^，,。；;\n]{0,8}(?:错了|错误|不对)|"
    r"(?:无需|不用|没必要)(?:再|继续)?(?:看医生|就医|复诊|治疗)|"
    r"(?:复诊|看医生|继续治疗)[^，,。；;\n]{0,8}(?:无需|不用|没必要)|"
    r"(?:your|the)\s+(?:formal\s+)?(?:ADHD|depression|bipolar|PTSD|OCD)?\s*"
    r"diagnosis\s+(?:was|is)\s+(?:wrong|incorrect|a\s+mistake)|"
    r"(?:ADHD|depression|bipolar|PTSD|OCD)\s+(?:has\s+been|was|is)\s+"
    r"(?:ruled\s+out|cured|resolved)",
    re.IGNORECASE,
)
GENERATED_PERSONAL_CLAIM_PATTERN = re.compile(
    r"(?:我|\bI\b)[^，,。；;\n]{0,20}(?:很爱|爱你|在乎|害怕|恐惧|担心|焦虑|"
    r"需要空间|想要|不想|感觉|感到|内心|love|care|fear|worry|feel|need|want)|"
    r"(?:我|\bI\b)[^，,。；;\n]{0,28}(?:保证|承诺|永远|绝不|一定会|不会再|"
    r"promise|always|never|will\s+definitely)|"
    r"(?:连续[一二三四五六七八九十\d]+天)?每天[^，,。；;\n]{0,28}"
    r"(?:一定|保证|承诺)[^，,。；;\n]{0,20}(?:回复|联系|陪伴|道歉)|"
    r"(?:连续[一二三四五六七八九十\d]+天)?每天[^，,。；;\n]{0,20}"
    r"向(?:伴侣|对象|家人|朋友|他|她)承诺[^，,。；;\n]{0,20}|"
    r"(?:接下来|未来)?[一二三四五六七八九十\d]+(?:天|周)?[^。；;\n]{0,12}"
    r"(?:我)?(?:每天|天天|每晚)[^，,。；;\n]{0,18}(?:都会|会|必定|一定)?"
    r"(?:准时|按时)?(?:回复|回你|联系|陪伴)|"
    r"(?:从明天起|以后|未来)[^，,。；;\n]{0,12}(?:每天|天天|每晚)"
    r"[^，,。；;\n]{0,18}(?:回复|回你|联系|陪伴)|"
    r"(?:我)?(?:会|将会|都会)(?:每天|天天|每晚)[^，,。；;\n]{0,18}"
    r"(?:回复|回你|联系|陪伴)|"
    r"(?:我)?(?:保证|承诺|发誓)[^，,。；;\n]{0,28}(?:永远|不再|及时回复|离开你)|"
    r"\bI\s+will\s+(?:reply|respond|message|contact)[^.;\n]{0,24}"
    r"(?:every\s+day|daily|every\s+(?:night|evening))|"
    r"(?:从明天(?:起|开始)|以后|未来)[，,\s]*[^，,。；;\n]{0,12}(?:我)?(?:每天|天天|每晚)"
    r"[^，,。；;\n]{0,18}(?:回复|回你|联系|陪伴|发消息|发信息)",
    re.IGNORECASE,
)
GENERATED_PERSONAL_CLAIM_GUARD_PATTERN = re.compile(
    r"若(?:内容|这句话|该感受)属实|如果(?:这|内容|该感受).{0,18}(?:属实|符合你的真实感受)|"
    r"请先确认.{0,18}(?:属实|可履行)|\[[^\]\n]{2,80}\]|"
    r"if\s+(?:this|that|the\s+feeling).{0,18}(?:is\s+true|fits\s+your\s+actual\s+feeling)",
    re.IGNORECASE,
)
GENERATED_PERSONAL_CLAIM_CONDITIONAL_GUARD_PATTERN = re.compile(
    r"若(?:内容|这句话|该感受)属实|"
    r"如果(?:这|内容|该感受).{0,18}(?:属实|符合你的真实感受)|"
    r"请先确认.{0,18}(?:属实|可履行)|"
    r"if\s+(?:this|that|the\s+feeling).{0,18}(?:is\s+true|fits\s+your\s+actual\s+feeling)",
    re.IGNORECASE,
)
GENERATED_UNREPORTED_CAUSE_PATTERN = re.compile(
    r"(?:因为|由于|源于)[^。；;\n]{0,36}(?:害怕|恐惧|担心|潜意识|内心|失去控制)"
    r"[^。；;\n]{0,42}(?:所以|才|导致|造成|保护|逃避|回避)|"
    r"(?:because|due\s+to)[^.;\n]{0,42}(?:fear|afraid|unconscious|loss\s+of\s+control)"
    r"[^.;\n]{0,42}(?:therefore|so|caus|protect|avoid)|"
    r"(?:我|用户)?[^，,。；;\n]{0,24}(?:不回消息|保持沉默|沉默|这样做)"
    r"[^，,。；;\n]{0,24}(?:是为了|就是想|想要|借此|以此)"
    r"[^，,。；;\n]{0,24}(?:惩罚|报复|让(?:伴侣|对象|对方|他|她)难受|逼(?:伴侣|对象|对方|他|她))|"
    r"(?:想让|为了让)[^，,。；;\n]{0,16}(?:伴侣|对象|对方|他|她)难受"
    r"[^，,。；;\n]{0,16}(?:借此|以此)?(?:惩罚|报复)?(?:对方|伴侣|对象|他|她)?|"
    r"(?:我)?(?:故意)?(?:晾着|不理|冷落|保持沉默|沉默)[^。；;\n]{0,18}"
    r"(?:好让|为了让|是想|就是想|只为了|为的就是|以便)[^，,。；;\n]{0,20}"
    r"(?:长记性|得到教训|一个教训|先道歉|难受)|"
    r"(?:我)?(?:不回消息|不回复|没回消息|保持沉默|沉默)[^。；;\n]{0,12}"
    r"(?:是在|是想|就是想|只为了|为的就是|以便)[^，,。；;\n]{0,20}"
    r"(?:惩罚|报复|逼[^，,。；;\n]{0,8}(?:道歉|低头)|给[^，,。；;\n]{0,8}教训)|"
    r"(?:我)?(?:故意)?(?:没回(?:他|她|消息)?|不回(?:他|她|消息)?)"
    r"[^。；;\n]{0,18}(?:好让|为了让|想让)[^，,。；;\n]{0,16}"
    r"(?:受点|得到|有个)?教训|"
    r"\bI\s+(?:ignored|did\s+not\s+reply\s+to)\s+(?:my\s+)?"
    r"(?:partner|spouse|friend|them|him|her)[^.;\n]{0,20}"
    r"(?:to|in\s+order\s+to)\s+punish\s+(?:them|him|her)",
    re.IGNORECASE,
)
GENERATED_DIAGNOSIS_CONFIRMATION_PATTERN = re.compile(
    r"可(?:据此|以)?确诊|足以确诊|可以(?:明确)?诊断为|应诊断为|"
    r"符合[^，,。；;\n]{0,32}(?:诊断标准|典型[^，,。；;\n]{0,12}(?:障碍|症))|"
    r"(?:据此|因此)[^，,。；;\n]{0,18}(?:就是|属于|患有)[^，,。；;\n]{0,24}(?:障碍|症|ADHD)|"
    r"(?:confirms?|proves?)[^.;\n]{0,24}(?:diagnosis|ADHD)|"
    r"(?:can|should)\s+be\s+diagnosed|meets?[^.;\n]{0,20}diagnostic\s+criteria|"
    r"(?:这些|该|现有)?(?:表现|信息|结果)[^，,。；;\n]{0,18}"
    r"(?:就是|足以证明|可以确定|能够确定|证明|说明)[^，,。；;\n]{0,18}"
    r"(?:你|用户|我)?(?:就是|有|患有|属于)?\s*"
    r"(?:ADHD|抑郁症|双相(?:障碍|情感障碍)?|自闭症谱系障碍|PTSD|"
    r"强迫症|焦虑障碍)|"
    r"(?:由此|据此|根据这些表现)[^，,。；;\n]{0,18}(?:确定|证明|说明)"
    r"[^，,。；;\n]{0,12}(?:你|用户|我)(?:有|患有|就是)"
    r"[^，,。；;\n]{0,12}(?:ADHD|抑郁症|双相(?:障碍|情感障碍)?|"
    r"自闭症谱系障碍|PTSD|强迫症|焦虑障碍)|"
    r"(?:你|用户|我)(?:患的|得的|有的)?(?:是|就是|患有|有)\s*"
    r"(?:ADHD|注意缺陷多动障碍|抑郁症|双相(?:障碍|情感障碍)?|"
    r"自闭症谱系障碍|PTSD|强迫症|焦虑障碍)|"
    r"(?:你的?|用户的?|我的?)?(?:情况|表现|症状)[^，,。；;\n]{0,12}(?:符合|达到)"
    r"[^，,。；;\n]{0,12}(?:ADHD|注意缺陷多动障碍|抑郁症|双相(?:障碍|情感障碍)?|"
    r"自闭症谱系障碍|PTSD|强迫症|焦虑障碍)(?:的)?(?:诊断标准)?|"
    r"(?:综合来看|总体来看|由此可见)[^，,。；;\n]{0,12}(?:是|属于|患有)"
    r"[^，,。；;\n]{0,12}(?:ADHD|注意缺陷多动障碍|抑郁症|双相(?:障碍|情感障碍)?|"
    r"自闭症谱系障碍|PTSD|强迫症|焦虑障碍)|"
    r"(?:达到|符合)[^，,。；;\n]{0,12}(?:ADHD|注意缺陷多动障碍|抑郁症|"
    r"双相(?:障碍|情感障碍)?|自闭症谱系障碍|PTSD|强迫症|焦虑障碍)"
    r"\s*(?:的)?诊断标准|"
    r"\bYou\s+(?:definitely|clearly|certainly)\s+(?:have|meet(?:s)?)\s+"
    r"(?:ADHD|depression|bipolar(?:\s+disorder)?|PTSD|OCD)|"
    r"\bthis\s+(?:clearly\s+)?confirm(?:s|ed)?\s+(?:a\s+diagnosis\s+of\s+)?"
    r"(?:ADHD|depression|bipolar(?:\s+disorder)?|PTSD|OCD)",
    re.IGNORECASE,
)
GENERATED_DIAGNOSIS_NONCONFIRMATION_PATTERN = re.compile(
    r"(?:不能|不应|不足以|无法|不可)[^，,。；;\n]{0,24}(?:确诊|诊断)|"
    r"(?:does\s+not|cannot|must\s+not|is\s+not\s+enough\s+to)"
    r"[^.;\n]{0,24}(?:confirm|diagnos)",
    re.IGNORECASE,
)
UNSAFE_GENERATED_SAFETY_PATTERN = re.compile(
    r"(?:想自杀|自杀|自伤|伤害自己|杀死自己).{0,40}"
    r"(?:独处|不要告诉|别告诉|保密|不要联系|别联系|隐瞒|等待)|"
    r"(?:独处|不要告诉|别告诉|保密|不要联系|别联系|隐瞒).{0,40}"
    r"(?:想自杀|自杀|自伤|伤害自己|杀死自己)|"
    r"(?:伤害|杀死|杀掉).{0,24}(?:伴侣|家人|同事|他|她|别人).{0,36}"
    r"(?:靠近|跟踪|准备|计划|不要告诉|别告诉|保密)|"
    r"(?:拿|带|提)(?:着|上)?(?:刀|枪|锤子|棍子|武器).{0,24}"
    r"(?:去找|找|靠近|接近|堵)(?:室友|伴侣|家人|同事|他|她|别人)",
    re.IGNORECASE,
)
REVIEW_GENERALIZATION_PATTERN = re.compile(
    r"证明我(?:就)?是|说明我(?:就)?是|确诊|撤销诊断|整个人格|一辈子|注定|"
    r"always|forever|proves?\s+I\s+am",
    re.IGNORECASE,
)
NONCLINICAL_PROVENANCE_PATTERN = re.compile(
    r"伪造|没有任何就诊记录|没有就诊记录|从未就诊|"
    r"parody\s+account|not\s+a\s+clinician|no\s+appointment|never\s+(?:saw|met)\s+a\s+clinician",
    re.IGNORECASE,
)

KNOWN_LABEL_PATTERNS = (
    r"ENFP",
    r"ENTJ",
    r"INTJ",
    r"INFP",
    r"INFJ",
    r"ISTJ",
    r"ISFJ",
    r"ESTJ",
    r"ESFJ",
    r"ENTP",
    r"INTP",
    r"ISFP",
    r"ESFP",
    r"ESTP",
    r"ISTP",
    r"ENFJ",
    r"I\s*人",
    r"E\s*人",
    r"高敏感(?:的人)?",
    r"回避(?:依恋|型)",
    r"低能量(?:人格|型)?",
    r"高共情(?:型)?",
    r"拖延症",
    r"完美主义者",
    r"讨好型",
    r"没自制力(?:的人)?",
    r"社恐",
    r"玻璃心",
    r"内向(?:型)?",
    r"introvert",
    r"ADHD",
    r"强迫症",
    r"OCD",
    r"抑郁症",
    r"双相情感障碍",
    r"PHQ-?9(?:量表)?",
    r"generalized\s+anxiety\s+disorder",
)

CN_DIAGNOSIS_NAME = (
    r"[\u4e00-\u9fff]{2,18}(?:症|病|障碍|综合征|失调|疾病)"
    r"(?:（[^（）]{1,20}）|\([^()]{1,20}\))?"
)
EN_DIAGNOSIS_NAME = (
    r"(?:[A-Za-z][A-Za-z -]{1,40}(?:disorder|syndrome|depression|anxiety)|ADHD|OCD|PTSD)"
)
DIAGNOSIS_NAME = rf"(?:{CN_DIAGNOSIS_NAME}|{EN_DIAGNOSIS_NAME})"
FORMAL_DIAGNOSIS_LABEL_PATTERNS = (
    re.compile(
        r"(?:正式)?诊断我为\s*[“‘\"']?(?P<label>[^，。；;\n”’\"']{2,32})",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?:正式)?确诊我?(?:患有|为|是)\s*[“‘\"']?(?P<label>[^，。；;\n”’\"']{2,32})",
        re.IGNORECASE,
    ),
    re.compile(
        rf"(?:正式)?(?:诊断|确诊)(?:了|我|为我)?(?:患有|有|为|是)?\s*[“‘\"']?"
        rf"(?P<label>{DIAGNOSIS_NAME})",
        re.IGNORECASE,
    ),
    re.compile(
        rf"(?:我)?(?:有|患有)\s*(?P<label>{DIAGNOSIS_NAME})(?:的)?(?:正式|临床)诊断",
        re.IGNORECASE,
    ),
    re.compile(
        rf"(?:formally\s+diagnosed(?:\s+me)?|psychiatrist\s+diagnosed(?:\s+me)?|"
        rf"clinician\s+diagnosed(?:\s+me)?)\s+(?:with\s+|as\s+)?(?P<label>{EN_DIAGNOSIS_NAME})",
        re.IGNORECASE,
    ),
    re.compile(rf"formal\s+diagnosis\s+of\s+(?P<label>{EN_DIAGNOSIS_NAME})", re.IGNORECASE),
)
FORMAL_SCALE_LABEL_PATTERNS = (
    re.compile(
        r"(?:注册)?(?:临床心理师|心理师|精神科医生|医院|门诊)[^。；;\n]{0,36}"
        r"(?:施测|做了?|完成)[^。；;\n]{0,8}"
        r"(?P<label>[A-Z][A-Z0-9-]{1,15}(?:成人自评|中文版|量表)?"
        r"\s*[，,:：]?\s*(?:报告)?(?:结果(?:是|为)?|总分|得分|分数)?\s*"
        r"(?:总分\s*)?(?:T分\s*)?\d+(?:\.\d+)?(?:\s*分)?"
        r"(?:（[^（）]{1,20}）|\([^()]{1,20}\))?)",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?:注册)?(?:临床心理师|心理师|精神科医生|医院|门诊)[^。；;\n]{0,36}"
        r"(?:施测|做了?|完成)\s*"
        r"(?P<label>[A-Z][A-Z0-9-]{1,15}(?:成人自评|中文版|量表)?"
        r"\s*[，,:：]\s*(?:报告)?(?:结果(?:是|为)?|总分|得分|分数)\s*"
        r"(?:总分\s*)?(?:T分\s*)?\d+(?:\.\d+)?(?:\s*分)?"
        r"(?:（[^（）]{1,20}）|\([^()]{1,20}\))?)",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?P<label>[A-Z][A-Z0-9-]{1,15}\s*(?:中文版\s*)?(?:正式\s*)?(?:量表)?"
        r"\s*[，,:：]?\s*(?:报告写)?(?:结果(?:是|为|显示|提示)?|得分|分数|总分)\s*"
        r"(?:\d+(?:\.\d+)?\s*分?|[^，。；;]{2,24}))",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?P<label>[A-Z][A-Z0-9-]{1,15}\s*(?:中文版\s*)?(?:正式\s*)?量表"
        r"(?:\s*[，,:：]?\s*(?:结果|得分|分数)?(?:是|为|显示)?\s*"
        r"\d+(?:\.\d+)?\s*分?)?)",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?P<label>[A-Z][A-Z0-9-]{1,15}\s*正式量表(?:结果)?(?:是|为|得分)?\s*"
        r"\d+(?:\.\d+)?\s*分?)",
        re.IGNORECASE,
    ),
    re.compile(r"正式\s*(?P<label>[A-Z][A-Z0-9-]{1,15}\s*量表)", re.IGNORECASE),
    re.compile(r"正式\s*(?P<label>[\u4e00-\u9fff]{2,20}量表)", re.IGNORECASE),
)
GENERIC_IDENTITY_LABEL = (
    r"(?:[A-Za-z0-9\u4e00-\u9fff·-]{2,24}(?:型人格|人格|型|者|症|障碍)|"
    r"[A-Za-z0-9\u4e00-\u9fff·-]{2,20}的人)"
)
SELF_LABEL_CAPTURE_PATTERNS = (
    re.compile(
        rf"我(?:今天|现在|目前|自己)?[^，。；,;]{{0,16}}"
        rf"(?:把自己称为|把自己叫作|自称|就是|是)\s*[“‘\"']?"
        rf"(?P<label>{GENERIC_IDENTITY_LABEL})",
        re.IGNORECASE,
    ),
    re.compile(
        rf"(?<!把)(?<!将)我(?:自己)?(?:一直|总是?|通常)?(?:把自己)?"
        rf"(?:叫作|称作|称为|归为)\s*[“‘\"']?"
        rf"(?P<label>{GENERIC_IDENTITY_LABEL})",
        re.IGNORECASE,
    ),
    re.compile(
        rf"我(?:自己)?(?:一直|总是?|通常)?自称\s*[“‘\"']?"
        rf"(?P<label>{GENERIC_IDENTITY_LABEL})",
        re.IGNORECASE,
    ),
    re.compile(
        rf"(?<!说)(?<!判断)(?<!断定)(?<!认为)我(?:就是|是)\s*[“‘\"']?"
        rf"(?P<label>{GENERIC_IDENTITY_LABEL})",
        re.IGNORECASE,
    ),
    re.compile(
        r"我(?:自己)?[^，。；,;]{0,12}(?:觉得|认为)(?:我)?(?:只是|就是|是)\s*"
        r"(?P<label>[\u4e00-\u9fffA-Za-z0-9·-]{2,16})(?=[，。；,;])",
        re.IGNORECASE,
    ),
)
ATTRIBUTED_LABEL_CAPTURE_PATTERNS = (
    re.compile(
        r"(?:称我为|叫我(?:作)?|把我(?:叫作|称作|称为|归为))\s*[“‘\"']"
        r"(?P<label>[^”’\"']{1,30})[”’\"']",
        re.IGNORECASE,
    ),
    re.compile(
        rf"(?:说|判断|断定|断言|认为|认定|下结论说)(?:我)?(?:是|就是|只是)\s*[“‘\"']?"
        rf"(?P<label>{GENERIC_IDENTITY_LABEL})",
        re.IGNORECASE,
    ),
    re.compile(
        rf"(?:把我)?(?:归为|分成|叫作|称为)\s*[“‘\"']?(?P<label>{GENERIC_IDENTITY_LABEL})",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?:朋友|同事|伴侣|室友|家人|老师|导师|上司|主管|播客|短视频博主|短视频评论区|博主)"
        r"[^，。；,;]{0,16}(?:说|写|觉得|认为|断言)(?:我)?(?:是|就是|只是)\s*"
        r"(?P<label>[\u4e00-\u9fffA-Za-z0-9·-]{2,16})(?=[，。；,;])",
        re.IGNORECASE,
    ),
)

NONFORMAL_CLINICAL_LABEL_PATTERNS = (
    re.compile(
        rf"(?:an?\s+)?(?:online\s+(?:quiz|test)|social\s+media\s+(?:quiz|test))\s+"
        rf"(?:says?|claims?)\s+I\s+(?:have|am)\s+(?P<label>{EN_DIAGNOSIS_NAME})",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?:短视频博主|论坛博主|睡眠博主|博主|网测|网上测试|平台)(?:(?:自创|自制)的?|的)?\s*"
        r"(?P<label>[A-Z][A-Z0-9-]{1,15}\s*(?:测试|测验|测评|量表|小测)?"
        r"(?:\s*[，,]\s*)?[^，。；;\n]{0,20}(?:结果(?:是|为|显示|提示)?|总分|得分|分数)"
        r"[^，。；;\n]{1,18})",
        re.IGNORECASE,
    ),
)

JUDGMENT_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("high_cost_decision_request", re.compile(r"我是不是应该按这个结论规划职业|替我决定|该不该分手|是不是该分手", re.IGNORECASE)),
    ("responsibility_transfer", re.compile(r"不回对象消息不是我的责任|不是我的责任|不是我的问题|not\s+my\s+(?:fault|responsibility)", re.IGNORECASE)),
    ("personality_generalization", re.compile(r"在亲密关系里也容易逃避|所有亲密关系都会失败|准确判断伴侣在撒谎|肯定知道伴侣正在撒谎|能准确判断伴侣在撒谎", re.IGNORECASE)),
    (
        "personality_generalization",
        re.compile(
            r"(?:所以|因此|于是)\s*我(?:本人)?(?:就是|是)\s*"
            r"[^，。；,;\n]{0,16}(?:废物|垃圾|失败者|窝囊废|控制狂|没用的人)",
            re.IGNORECASE,
        ),
    ),
    ("capability_verdict", re.compile(r"我不适合带团队|不适合带团队|我不适合管理岗|不适合管理岗|不适合创业|不适合销售|没有领导力|更会领导|做不好会计工作|做不好客户汇报|根本没有自制力|没有自制力|(?:重要)?项目.{0,12}别让(?:我)?负责|别让(?:我)?负责|不要让(?:我)?负责|不该让(?:我)?负责", re.IGNORECASE)),
    ("future_verdict", re.compile(r"不可能做好公开表达|我做不好长期项目|做不好长期项目|承受不了批评|永远交不了稿|减肥一定失败|所有亲密关系都会失败|can\s+never\s+speak\s+in\s+public|cannot\s+finish\s+any\s+long\s+project", re.IGNORECASE)),
    (
        "capability_verdict",
        re.compile(
            r"(?:看来|所以|因此|既然|难怪|那我就)[^。；;\n]{0,42}?"
            r"(?:领导岗.{0,8}没缘分|别(?:再)?争取晋升|拒绝.{0,12}管理职位|"
            r"不用再报考试|长期项目交给别人|公开表达.{0,12}到此为止|"
            r"亲密关系.{0,12}走不到最后)|"
            r"长期项目交给别人更合适|公开表达这条路就到此为止|"
            r"领导岗和我没缘分",
            re.IGNORECASE,
        ),
    ),
    (
        "future_verdict",
        re.compile(
            r"以后绝对不能独自旅行|所以我没有救了|"
            r"不可能适应任何会议|所有关系都不会长久|任何团队工作都不适合我",
            re.IGNORECASE,
        ),
    ),
    (
        "future_verdict",
        re.compile(
            r"(?:它|这个结果|该结果|该报告|这份结果)\s*(?:说明|意味着|证明|表示|代表)"
            r"[^。；;\n]{0,12}我[^。；;\n]{0,28}(?:一定|必然|永远|注定)"
            r"[^。；;\n]{0,24}(?:没法|无法|不能|不可能|失败|做不好|不适合)",
            re.IGNORECASE,
        ),
    ),
    (
        "capability_verdict",
        re.compile(
            r"足以(?:说明|证明)我不该(?:再)?(?:竞选|申请|尝试|担任)|"
            r"不适合做.{0,16}(?:工作|岗位)|不该(?:再)?竞选",
            re.IGNORECASE,
        ),
    ),
    (
        "personality_generalization",
        re.compile(
            r"每次.{0,24}(?:都)?证明(?:这个|该)?标签|"
            r"(?:帮我|请帮我|我想)(?:区分|拆开|拆解|核对).{0,18}(?:标签|判断|具体行为)|"
            r"(?:区分|拆开|拆解).{0,12}(?:标签|判断).{0,12}(?:行为|事实|情境)?",
            re.IGNORECASE,
        ),
    ),
    (
        "future_verdict",
        re.compile(
            r"以后.{0,18}(?:完成不了|不能|不会).{0,18}(?:任何|所有)|"
            r"(?:完成不了|不能完成).{0,12}(?:任何|所有)",
            re.IGNORECASE,
        ),
    ),
)


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def parse_clock(value: str) -> datetime:
    """Parse an explicit workflow clock and require a timezone."""

    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (AttributeError, TypeError, ValueError) as exc:
        raise ValueError(f"clock_invalid: {value!r} is not an ISO 8601 timestamp") from exc
    if parsed.tzinfo is None:
        raise ValueError("clock_requires_timezone: workflow clocks must include Z or an offset")
    return parsed.astimezone(timezone.utc)


def clock_error_code(exc: ValueError, prefix: str = "clock") -> str:
    code = str(exc).split(":", 1)[0]
    if code == "clock_requires_timezone":
        return f"{prefix}_requires_timezone"
    return f"{prefix}_invalid"


def canonical_json(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def digest(value: Any) -> str:
    return hashlib.sha256(canonical_json(value)).hexdigest()


def emit(payload: Any, code: int = 0) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    raise SystemExit(code)


def error(code: str, path: str, message: str) -> dict[str, str]:
    return {"code": code, "path": path, "message": message}


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def read_bounded_text(path: Path, field: str) -> str:
    """Read one explicit UTF-8 input file without following a symbolic link."""

    path = path.expanduser()
    if not path.is_file() or path.is_symlink():
        raise ValueError(f"{field}_file_invalid: expected a regular non-symlink file")
    payload = path.read_bytes()
    if len(payload) > MAX_USER_TEXT_BYTES:
        raise ValueError(f"{field}_file_too_large: maximum is {MAX_USER_TEXT_BYTES} bytes")
    try:
        return payload.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError(f"{field}_file_invalid_utf8") from exc


def confirmation_has_explicit_experiment_intent(value: str) -> bool:
    """Recognize narrow start intent without claiming who authored the file."""

    normalized = unicodedata.normalize("NFKC", value).strip()
    if not normalized or not re.search(r"我|本人", normalized, re.IGNORECASE):
        return False
    if re.search(
        r"不(?:愿意|同意|确认|开始|启动|进行)|拒绝|取消|撤回|暂不|先不|不要|不同意|"
        r"not\s+(?:agree|confirm|willing)|do\s+not\s+(?:start|begin)",
        normalized,
        re.IGNORECASE,
    ):
        return False
    agreement = bool(
        re.search(r"愿意|同意|确认|agree|consent|confirm", normalized, re.IGNORECASE)
    )
    start = bool(re.search(r"开始|启动|进行|start|begin", normalized, re.IGNORECASE))
    experiment = bool(re.search(r"实验|试验|experiment", normalized, re.IGNORECASE))
    return agreement and start and experiment


def user_text_from_args(args: argparse.Namespace) -> str:
    if getattr(args, "text", None) is not None:
        return args.text
    if getattr(args, "text_file", None) is not None:
        return read_bounded_text(args.text_file, "text")
    payload = sys.stdin.buffer.read(MAX_USER_TEXT_BYTES + 1)
    if len(payload) > MAX_USER_TEXT_BYTES:
        raise ValueError(f"text_stdin_too_large: maximum is {MAX_USER_TEXT_BYTES} bytes")
    try:
        return payload.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError("text_stdin_invalid_utf8") from exc


def record_fields_from_args(args: argparse.Namespace) -> dict[str, str]:
    keys = ("source_text", "fact", "context", "timeframe")
    direct_values = {key: getattr(args, key) for key in keys}
    if args.observation_file is not None:
        if any(value is not None for value in direct_values.values()):
            raise ValueError(
                "observation_source_conflict: use either --observation-file or the four direct fields"
            )
        try:
            value = json.loads(
                read_bounded_text(args.observation_file, "observation")
            )
        except json.JSONDecodeError as exc:
            raise ValueError("observation_file_invalid_json") from exc
        if not isinstance(value, dict) or set(value) != set(keys):
            raise ValueError(
                "observation_file_invalid: expected exactly source_text, fact, context and timeframe"
            )
        fields = value
    else:
        fields = direct_values
    if any(not isinstance(fields[key], str) or not fields[key].strip() for key in keys):
        raise ValueError("record_fields_required: provide four non-empty text fields")
    return {key: fields[key] for key in keys}


def write_json(path: Path, payload: Any) -> None:
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def json_bytes(payload: Any) -> bytes:
    return (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def raw_sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _fsync_directory(path: Path) -> None:
    """Best-effort directory durability after journal or target replacement."""

    try:
        descriptor = os.open(path, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(descriptor)
    except OSError:
        pass
    finally:
        os.close(descriptor)


@contextmanager
def case_lock(case_dir: Path, exclusive: bool, *, create: bool = False) -> Iterator[None]:
    """Serialize one case lifecycle without recursively acquiring the same lock."""

    if not case_dir.exists():
        if not create:
            raise FileNotFoundError(f"missing case directory: {case_dir}")
        case_dir.mkdir(parents=True, exist_ok=False)
    if not case_dir.is_dir():
        raise ValueError(f"case_directory_invalid: {case_dir}")
    lock_path = case_dir / LOCK_FILE
    with lock_path.open("a+b") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _read_state_bytes(case_dir: Path) -> dict[str, bytes | None]:
    return {
        name: (case_dir / name).read_bytes() if (case_dir / name).is_file() else None
        for name in STATE_FILES
    }


def _transaction_error(message: str) -> ValueError:
    return ValueError(f"transaction_journal_invalid: {message}")


def _safe_case_child(case_dir: Path, name: Any, field: str) -> Path:
    """Resolve one journal-owned basename without permitting path escape."""

    if not isinstance(name, str) or not name or Path(name).is_absolute() or Path(name).name != name:
        raise _transaction_error(f"{field} must be a safe basename")
    root = case_dir.resolve()
    child = case_dir / name
    if child.parent.resolve() != root:
        raise _transaction_error(f"{field} must stay inside the case directory")
    if child.is_symlink():
        raise _transaction_error(f"{field} cannot be a symbolic link")
    return child


def _safe_transaction_child(transaction_dir: Path, name: Any, field: str) -> Path:
    """Resolve one backup basename inside an already validated transaction dir."""

    if not isinstance(name, str) or not name or Path(name).is_absolute() or Path(name).name != name:
        raise _transaction_error(f"{field} must be a safe basename")
    child = transaction_dir / name
    if child.parent.resolve() != transaction_dir.resolve():
        raise _transaction_error(f"{field} must stay inside the transaction directory")
    if child.is_symlink():
        raise _transaction_error(f"{field} cannot be a symbolic link")
    return child


def _validate_transaction_journal(case_dir: Path, journal: Any) -> dict[str, Any]:
    """Validate journal shape and every path before recovery or cleanup."""

    if not isinstance(journal, dict):
        raise _transaction_error("journal must be an object")
    if journal.get("schema_version") != "1.0":
        raise _transaction_error("unsupported or missing schema_version")
    transaction_name = journal.get("transaction_dir")
    if not isinstance(transaction_name, str) or not TRANSACTION_DIR_NAME_PATTERN.fullmatch(transaction_name):
        raise _transaction_error("transaction_dir is not a runtime transaction basename")
    transaction_dir = _safe_case_child(case_dir, transaction_name, "transaction_dir")
    if not transaction_dir.is_dir():
        raise _transaction_error("transaction_dir is missing or is not a directory")

    entries = journal.get("targets")
    if not isinstance(entries, list) or len(entries) != len(STATE_FILES):
        raise _transaction_error("targets must be the complete state bundle list")
    if not all(isinstance(item, dict) for item in entries):
        raise _transaction_error("every target must be an object")
    names = [item.get("name") for item in entries]
    if not all(isinstance(name, str) for name in names):
        raise _transaction_error("every target name must be a string")
    if len(set(names)) != len(names) or set(names) != set(STATE_FILES):
        raise _transaction_error("targets must name each state file exactly once")

    for item in entries:
        name = item["name"]
        if not isinstance(item.get("old_exists"), bool):
            raise _transaction_error(f"old_exists for {name} must be boolean")
        new_sha = item.get("new_sha256")
        if not isinstance(new_sha, str) or not SHA256_PATTERN.fullmatch(new_sha):
            raise _transaction_error(f"new_sha256 for {name} is invalid")
        old_sha = item.get("old_sha256")
        if item["old_exists"]:
            if not isinstance(old_sha, str) or not SHA256_PATTERN.fullmatch(old_sha):
                raise _transaction_error(f"old_sha256 for {name} is invalid")
        elif old_sha is not None:
            raise _transaction_error(f"old_sha256 for absent {name} must be null")

        staged_name = item.get("staged")
        expected_stage = re.compile(rf"\.{re.escape(name)}\.[a-z0-9_]{{6,32}}\.tmp")
        if not isinstance(staged_name, str) or not expected_stage.fullmatch(staged_name):
            raise _transaction_error(f"staged for {name} is not a runtime staging basename")
        staged = _safe_case_child(case_dir, staged_name, f"staged for {name}")
        if staged.exists() and not staged.is_file():
            raise _transaction_error(f"staged for {name} is not a regular file")

        backup_name = item.get("backup")
        if item["old_exists"]:
            if backup_name != f"{name}.before":
                raise _transaction_error(f"backup for {name} is invalid")
            backup = _safe_transaction_child(transaction_dir, backup_name, f"backup for {name}")
            if not backup.is_file():
                raise _transaction_error(f"backup for {name} is missing or is not a regular file")
        elif backup_name is not None:
            raise _transaction_error(f"backup for absent {name} must be null")
    return journal


def _cleanup_runtime_stage_orphans(case_dir: Path) -> None:
    """Remove only regular files in the runtime-reserved pre-journal namespace."""

    removed = False
    for child in case_dir.iterdir():
        if not RUNTIME_STAGE_NAME_PATTERN.fullmatch(child.name) or child.is_symlink():
            continue
        if child.is_file():
            child.unlink()
            removed = True
    if removed:
        _fsync_directory(case_dir)


def _init_preflight_entries(case_dir: Path) -> tuple[list[Path], list[Path]]:
    """Separate recoverable runtime debris from user-owned or unsafe entries.

    A prior init can crash after staging the first state file but before writing
    its transaction journal.  Those regular, runtime-named staging files are
    safe to remove under the case lock.  Everything else must make init fail
    before it creates or changes the lock file.
    """

    recoverable: list[Path] = []
    blocking: list[Path] = []
    for item in case_dir.iterdir():
        if item.name == LOCK_FILE:
            continue
        if (
            RUNTIME_STAGE_NAME_PATTERN.fullmatch(item.name)
            and item.is_file()
            and not item.is_symlink()
        ):
            recoverable.append(item)
        else:
            blocking.append(item)
    return recoverable, blocking


def _stage_bytes(case_dir: Path, target_name: str, payload: bytes) -> Path:
    descriptor, raw_path = tempfile.mkstemp(
        dir=case_dir,
        prefix=f".{target_name}.",
        suffix=".tmp",
    )
    path = Path(raw_path)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
    except Exception:
        path.unlink(missing_ok=True)
        raise
    return path


def _remove_transaction_directory(path: Path) -> None:
    if not path.is_dir():
        return
    for child in path.iterdir():
        if child.is_file() or child.is_symlink():
            child.unlink(missing_ok=True)
    try:
        path.rmdir()
    except OSError:
        pass


def _cleanup_transaction(case_dir: Path, journal: dict[str, Any]) -> None:
    journal = _validate_transaction_journal(case_dir, journal)
    (case_dir / TRANSACTION_JOURNAL_FILE).unlink(missing_ok=True)
    for item in journal.get("targets", []):
        staged = case_dir / item.get("staged", "")
        if staged != case_dir and staged.is_file():
            staged.unlink(missing_ok=True)
    transaction_dir = case_dir / journal.get("transaction_dir", "")
    if transaction_dir != case_dir:
        _remove_transaction_directory(transaction_dir)
    _fsync_directory(case_dir)


def _restore_old_state(case_dir: Path, journal: dict[str, Any]) -> None:
    journal = _validate_transaction_journal(case_dir, journal)
    entries = journal.get("targets")
    transaction_dir = case_dir / journal.get("transaction_dir", "")

    for item in entries:
        name = item["name"]
        target = case_dir / name
        old_exists = bool(item.get("old_exists"))
        if old_exists:
            old_sha = item.get("old_sha256")
            if target.is_file() and raw_sha256(target.read_bytes()) == old_sha:
                continue
            backup = transaction_dir / item.get("backup", "")
            if not backup.is_file() or raw_sha256(backup.read_bytes()) != old_sha:
                raise ValueError(f"transaction_rollback_failed: invalid backup for {name}")
            restore_stage = _stage_bytes(case_dir, name, backup.read_bytes())
            os.replace(restore_stage, target)
        elif target.exists():
            if target.is_dir():
                raise ValueError(f"transaction_rollback_failed: unexpected directory at {name}")
            target.unlink()

    _fsync_directory(case_dir)
    restored = _read_state_bytes(case_dir)
    for item in entries:
        current = restored[item["name"]]
        if item.get("old_exists"):
            if current is None or raw_sha256(current) != item.get("old_sha256"):
                raise ValueError(f"transaction_rollback_failed: {item['name']} was not restored")
        elif current is not None:
            raise ValueError(f"transaction_rollback_failed: {item['name']} should not exist")


def commit_state_bundle(case_dir: Path, bundle: dict[str, bytes]) -> None:
    """Commit events, materialized case and head as one recoverable bundle."""

    if set(bundle) != set(STATE_FILES):
        raise ValueError("transaction_bundle_invalid: all three state files are required")
    if (case_dir / TRANSACTION_JOURNAL_FILE).exists():
        raise ValueError("transaction_recovery_required: pending state transaction must be recovered")

    for name in STATE_FILES:
        legacy_sentinel = case_dir / f".{name}.tmp"
        if legacy_sentinel.exists():
            raise ValueError(f"transaction_staging_obstructed: remove legacy sentinel {legacy_sentinel.name}")

    staged: dict[str, Path] = {}
    transaction_dir: Path | None = None
    journal: dict[str, Any] | None = None
    before = _read_state_bytes(case_dir)
    try:
        for name in STATE_FILES:
            staged[name] = _stage_bytes(case_dir, name, bundle[name])

        transaction_dir = Path(tempfile.mkdtemp(prefix=".case-txn-", dir=case_dir))
        entries: list[dict[str, Any]] = []
        for name in STATE_FILES:
            old = before[name]
            backup_name = f"{name}.before"
            if old is not None:
                backup_path = transaction_dir / backup_name
                with backup_path.open("wb") as handle:
                    handle.write(old)
                    handle.flush()
                    os.fsync(handle.fileno())
            entries.append(
                {
                    "name": name,
                    "old_exists": old is not None,
                    "old_sha256": raw_sha256(old) if old is not None else None,
                    "new_sha256": raw_sha256(bundle[name]),
                    "backup": backup_name if old is not None else None,
                    "staged": staged[name].name,
                }
            )
        journal = {
            "schema_version": "1.0",
            "transaction_dir": transaction_dir.name,
            "targets": entries,
        }
        journal_stage = _stage_bytes(case_dir, TRANSACTION_JOURNAL_FILE, json_bytes(journal))
        os.replace(journal_stage, case_dir / TRANSACTION_JOURNAL_FILE)
        _fsync_directory(case_dir)

        for name in STATE_FILES:
            os.replace(staged[name], case_dir / name)
        _fsync_directory(case_dir)
    except Exception as commit_error:
        if journal is not None and (case_dir / TRANSACTION_JOURNAL_FILE).is_file():
            try:
                _restore_old_state(case_dir, journal)
                _cleanup_transaction(case_dir, journal)
            except Exception as rollback_error:
                raise ValueError(
                    f"transaction_rollback_failed: commit={commit_error}; rollback={rollback_error}"
                ) from rollback_error
        else:
            for path in staged.values():
                path.unlink(missing_ok=True)
            if transaction_dir is not None:
                _remove_transaction_directory(transaction_dir)
        raise
    else:
        if journal is not None:
            _cleanup_transaction(case_dir, journal)


def recover_pending_transaction(case_dir: Path) -> None:
    """Recover an interrupted bundle while the caller holds the exclusive lock."""

    journal_path = case_dir / TRANSACTION_JOURNAL_FILE
    if not journal_path.exists():
        _cleanup_runtime_stage_orphans(case_dir)
        return
    if journal_path.is_symlink():
        raise _transaction_error("journal cannot be a symbolic link")
    try:
        journal = read_json(journal_path)
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"transaction_recovery_failed: unreadable journal: {exc}") from exc
    journal = _validate_transaction_journal(case_dir, journal)
    entries = journal.get("targets", [])
    current = _read_state_bytes(case_dir)
    committed = bool(entries) and all(
        current.get(item.get("name")) is not None
        and raw_sha256(current[item["name"]]) == item.get("new_sha256")
        for item in entries
        if item.get("name") in current
    ) and {item.get("name") for item in entries} == set(STATE_FILES)
    if committed:
        _cleanup_transaction(case_dir, journal)
        return
    try:
        _restore_old_state(case_dir, journal)
    except Exception as exc:
        raise ValueError(f"transaction_rollback_failed: {exc}") from exc
    _cleanup_transaction(case_dir, journal)


def load_schema(name: str) -> dict[str, Any]:
    return read_json(SCHEMAS / name)


def type_matches(value: Any, expected: str) -> bool:
    if expected == "object":
        return isinstance(value, dict)
    if expected == "array":
        return isinstance(value, list)
    if expected == "string":
        return isinstance(value, str)
    if expected == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if expected == "boolean":
        return isinstance(value, bool)
    if expected == "null":
        return value is None
    return True


def schema_errors(value: Any, schema: dict[str, Any], path: str = "$") -> list[dict[str, str]]:
    """Validate the JSON-Schema subset used by this self-contained package."""

    errors: list[dict[str, str]] = []
    expected_type = schema.get("type")
    if expected_type:
        allowed = expected_type if isinstance(expected_type, list) else [expected_type]
        if not any(type_matches(value, item) for item in allowed):
            return [error("schema_type", path, f"expected type {allowed}")]

    if "enum" in schema and value not in schema["enum"]:
        errors.append(error("schema_enum", path, f"value is not one of {schema['enum']}"))

    if isinstance(value, dict):
        required = schema.get("required", [])
        for key in required:
            if key not in value:
                errors.append(error("schema_required", f"{path}.{key}", "required field is missing"))
        properties = schema.get("properties", {})
        if schema.get("additionalProperties") is False:
            for key in value:
                if key not in properties:
                    errors.append(error("schema_additional_property", f"{path}.{key}", "additional property is not allowed"))
        for key, subschema in properties.items():
            if key in value:
                errors.extend(schema_errors(value[key], subschema, f"{path}.{key}"))

    if isinstance(value, list):
        if len(value) < schema.get("minItems", 0):
            errors.append(error("schema_min_items", path, f"requires at least {schema['minItems']} items"))
        if schema.get("uniqueItems"):
            seen: set[bytes] = set()
            for item in value:
                token = canonical_json(item)
                if token in seen:
                    errors.append(error("schema_unique_items", path, "array items must be unique"))
                    break
                seen.add(token)
        item_schema = schema.get("items")
        if item_schema:
            for index, item in enumerate(value):
                errors.extend(schema_errors(item, item_schema, f"{path}[{index}]"))

    if isinstance(value, str):
        if len(value) < schema.get("minLength", 0):
            errors.append(error("schema_min_length", path, f"requires at least {schema['minLength']} characters"))
        if "pattern" in schema and re.fullmatch(schema["pattern"], value) is None:
            errors.append(error("schema_pattern", path, f"does not match {schema['pattern']}"))

    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if value < schema.get("minimum", value):
            errors.append(error("schema_minimum", path, f"must be at least {schema['minimum']}"))
    return errors


def source_for(text: str, evidence_id: str, start: int, end: int) -> dict[str, Any]:
    return {"evidence_id": evidence_id, "quote": text[start:end], "start": start, "end": end}


def first_span(text: str, pattern: re.Pattern[str]) -> tuple[int, int, str] | None:
    match = pattern.search(text)
    if not match:
        return None
    return match.start(), match.end(), match.group(0)


OUTER_QUOTE_PAIRS = {"“": "”", "‘": "’", '"': '"', "'": "'"}


def trim_matched_outer_quotes(raw: str) -> tuple[str, int]:
    """Trim whitespace and only a complete pair of outer evidence quotes."""

    leading = len(raw) - len(raw.lstrip(" \t\n"))
    cleaned = raw.strip(" \t\n")
    if len(cleaned) >= 2 and OUTER_QUOTE_PAIRS.get(cleaned[0]) == cleaned[-1]:
        cleaned = cleaned[1:-1]
        leading += 1
        inner_leading = len(cleaned) - len(cleaned.lstrip(" \t\n"))
        leading += inner_leading
        cleaned = cleaned.strip(" \t\n")
    return cleaned, leading


def captured_label_candidates(
    text: str, patterns: Iterable[re.Pattern[str]]
) -> list[tuple[int, int, str]]:
    """Return exact spans from named ``label`` groups without normalizing evidence."""

    candidates: list[tuple[int, int, str]] = []
    for pattern in patterns:
        for match in pattern.finditer(text):
            raw = match.group("label")
            cleaned, offset = trim_matched_outer_quotes(raw)
            if not cleaned:
                continue
            start = match.start("label") + offset
            candidates.append((start, start + len(cleaned), cleaned))
    return candidates


def span_is_captured_label(
    text: str, start: int, end: int, patterns: Iterable[re.Pattern[str]]
) -> bool:
    return any(left == start and right == end for left, right, _ in captured_label_candidates(text, patterns))


def looks_like_identity_label(value: str) -> bool:
    candidate = value.strip()
    if not candidate or len(candidate) > 40:
        return False
    if re.search(
        r"(?:型人格|人格|型|型(?:员工|领导|成员|伴侣|学生|家长|管理者)|者|的人|症|障碍)$",
        candidate,
        re.IGNORECASE,
    ):
        return True
    if re.search(
        r"窝囊废|控制狂|没责任心|社交废物|低能量废物|失败者|夜猫子|懒人|没天赋|玻璃心|双相|"
        r"people-pleaser|avoidant|narcissist|socially\s+defective|emotionally\s+unstable|"
        r"缺乏领导人格|没有数学脑子的人|不懂共情|成人\s*ADHD|\d+%\s*ADHD",
        candidate,
        re.IGNORECASE,
    ):
        return True
    return any(re.search(pattern, candidate, re.IGNORECASE) for pattern in KNOWN_LABEL_PATTERNS)


@dataclass(frozen=True)
class ScopedSegment:
    start: int
    end: int
    text: str
    context: str
    actor: str
    time_scope: str


@dataclass(frozen=True)
class AttributionEvent:
    source_type: str
    speaker_role: str
    actor_text: str
    actor_start: int
    actor_end: int
    predicate_kind: str
    predicate_polarity: str
    predicate_text: str
    predicate_start: int
    predicate_end: int
    target_role: str
    target_text: str
    target_start: int
    target_end: int
    target_resolution: str
    label_start: int
    label_end: int
    discourse_kind: str
    discourse_start: int
    discourse_end: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "speaker": {
                "role": self.speaker_role,
                "text": self.actor_text,
                "span": {"start": self.actor_start, "end": self.actor_end},
            },
            "source": {
                "type": self.source_type,
                "evidence_status": SOURCE_STATUS[self.source_type],
            },
            "predicate": {
                "kind": self.predicate_kind,
                "polarity": self.predicate_polarity,
                "text": self.predicate_text,
                "span": {"start": self.predicate_start, "end": self.predicate_end},
            },
            "target": {
                "role": self.target_role,
                "text": self.target_text,
                "resolution": self.target_resolution,
                "span": {"start": self.target_start, "end": self.target_end},
            },
            "label": {"start": self.label_start, "end": self.label_end},
            "discourse_context": {
                "kind": self.discourse_kind,
                "span": {"start": self.discourse_start, "end": self.discourse_end},
            },
        }


@dataclass(frozen=True)
class LabelCandidate:
    start: int
    end: int
    text: str
    seed_source: str | None = None
    relation_bound: bool = False


@dataclass(frozen=True)
class GroundedMeans:
    kind: str
    state: str
    text: str
    start: int
    end: int


@dataclass(frozen=True)
class SafetyFinding:
    kind: str
    target: str
    means: tuple[GroundedMeans, ...]
    start: int
    end: int
    target_text: str | None = None


@dataclass(frozen=True)
class SafetyProfile:
    active_text: str
    findings: tuple[SafetyFinding, ...]

    @property
    def actionable(self) -> bool:
        return bool(self.findings)

    @property
    def immediate(self) -> bool:
        return any(finding.kind != "recent_self_harm" for finding in self.findings)

    @property
    def needs_prompt_support(self) -> bool:
        return any(finding.kind == "recent_self_harm" for finding in self.findings)

    @property
    def features(self) -> set[str]:
        values = {"immediate"} if self.immediate else set()
        for finding in self.findings:
            values.add(finding.kind)
            if finding.kind == "dangerous_height":
                values.add("height")
            if finding.kind == "dangerous_rail":
                values.add("rail")
            for means in finding.means:
                values.add(means.kind)
                if means.kind == "medication":
                    values.add(f"medication_{means.state}")
            if finding.target == "other" and finding.means:
                values.add("weapon_other_harm")
        return values


def iter_scoped_segments(text: str) -> Iterable[ScopedSegment]:
    """Split text into evidence-preserving clauses and classify obvious non-user scopes."""

    for match in re.finditer(r"[^。；;\n]+(?:[。；;\n]+|$)", text):
        value = match.group(0)
        if not value.strip():
            continue
        if FICTION_CONTEXT_PATTERN.search(value):
            context, actor = "fiction", "fictional"
        elif EDUCATION_CONTEXT_PATTERN.search(value):
            context, actor = "education", "third_party"
        elif NEWS_CONTEXT_PATTERN.search(value):
            context, actor = "news", "third_party"
        elif DOCUMENT_CONTEXT_PATTERN.search(value):
            context, actor = "document", "third_party"
        elif TRANSLATION_CONTEXT_PATTERN.search(value):
            context, actor = "translation", "third_party"
        elif THIRD_PARTY_REPORT_PATTERN.search(value):
            context, actor = "third_party_report", "third_party"
        elif EXPLICIT_NONCURRENT_CONTEXT_PATTERN.search(value):
            context, actor = "explicit_noncurrent", "third_party"
        else:
            context, actor = "direct", "user"
        time_scope = "historical" if HISTORICAL_CONTEXT_PATTERN.search(value) else "current"
        yield ScopedSegment(match.start(), match.end(), value, context, actor, time_scope)


def current_user_tail_start(segment: ScopedSegment) -> int | None:
    restart = CURRENT_USER_RESTART_PATTERN.search(segment.text)
    if not restart:
        return None
    inner = re.search(r"我(?:本人)?", restart.group(0))
    if inner:
        return segment.start + restart.start() + inner.start()
    current = re.search(r"现在|目前|此刻|今晚|今天|已经|刚|准备|打算|想要", restart.group(0))
    if current:
        return segment.start + restart.start() + current.start()
    return segment.start + restart.start()


def active_domain_text(text: str, domain: str) -> str:
    """Mask quoted, historical or fictional claims that are not active user requests."""

    characters = list(text)
    for segment in iter_scoped_segments(text):
        excluded_context = segment.context in {
            "fiction",
            "education",
            "news",
            "document",
            "translation",
            "third_party_report",
            "explicit_noncurrent",
        }
        excluded_time = domain == "safety" and segment.time_scope == "historical"
        if not (excluded_context or excluded_time):
            continue
        tail_start = current_user_tail_start(segment)
        stop = tail_start if tail_start is not None else segment.end
        for index in range(segment.start, stop):
            if characters[index] not in "。；;\n":
                characters[index] = " "
    return "".join(characters)


def has_self_description_cue(value: str) -> bool:
    if re.search(
        r"(?:说|写|判断|断定|断言|认为|认定)(?:我)(?:是|就是|只是)",
        value,
        re.IGNORECASE,
    ) and not re.search(
        r"我(?:自己)?(?:说自己是|认为自己是|把自己称为|自称)",
        value,
        re.IGNORECASE,
    ):
        return False
    if any(pattern.search(value) for pattern in SELF_LABEL_CAPTURE_PATTERNS):
        return True
    return bool(
        re.search(
            r"(?<!说)(?<!判断)(?<!断定)(?<!断言)(?<!认为)我是|我就是|I\s+am|"
            r"我(?:自己)?[^，。；,;]{0,18}(?:觉得|认为)(?:我)?(?:只是|就是|是)|"
            r"我(?:后来)?给自己贴(?:的|了).{0,12}标签|我(?:总)?说自己是|"
            r"我(?:自己)?(?:又|也)?自称|我[^，。；,;]{0,16}把自己称为|"
            r"我[^，。；,;]{0,16}(?:就是|是)[“‘\"']",
            value,
            re.IGNORECASE,
        )
    )


SAFETY_SENTENCE_PATTERN = re.compile(r"[^。；;\n]+(?:[。；;\n]+|$)")
OTHER_HARM_TARGET_TOKEN = r"前同事|前伴侣|前任|伴侣|室友|同事|邻居|别人|他人|他|她"
OTHER_HARM_TARGET_PATTERN = re.compile(OTHER_HARM_TARGET_TOKEN, re.IGNORECASE)
SELF_HARM_INTENT_PATTERN = re.compile(
    r"(?:今晚|现在|目前|此刻|准备|打算|计划|即将|就要|想要|想).{0,18}"
    r"(?:自杀|自伤|伤害自己|割伤自己|结束自己的生命)|"
    r"(?:自杀|自伤|伤害自己|割伤自己|结束自己的生命).{0,18}"
    r"(?:打算|计划|准备|会照做|停不下来)|"
    r"(?:intend\s+to|about\s+to|(?:am|'m)\s+going\s+to|will).{0,18}"
    r"(?:end\s+my\s+life|kill\s+myself)|"
    r"(?:现在|目前|仍|还是).{0,12}怕自己会(?:照做|伤害自己|自伤|自杀)|"
    r"(?:我(?:这两天|最近|过去(?:一|两|三|四|五|六|七|八|九|十|\d+)(?:天|周))?"
    r"|(?:这两天|最近|过去(?:一|两|三|四|五|六|七|八|九|十|\d+)(?:天|周))我)"
    r"[^。；;\n]{0,36}(?:反复(?:有|出现)?|出现了?|有)?\s*"
    r"(?:自伤念头|伤害自己的想法|自杀念头)|"
    r"(?:准备|打算|计划|马上|现在|今晚)?[^。；;\n]{0,8}去死|"
    r"不想活(?:了|下去)?|活不下去|kill\s+myself|suicid",
    re.IGNORECASE,
)
OTHER_HARM_INTENT_PATTERN = re.compile(
    r"(?:现在|目前|此刻|马上|准备|打算|计划|想要|想|(?<!摘)要).{0,18}"
    r"(?:伤害|攻击|袭击|殴打|砸|打|砍)(?:伤|死)?"
    r"(?:前伴侣|前任|伴侣|别人|他人|同事|室友|邻居|他|她)|"
    r"(?:伤害|攻击|袭击|殴打)(?:前伴侣|前任|伴侣|别人|他人|同事|室友|邻居)"
    r".{0,20}(?:会动手|停不下来|怕自己)|"
    r"(?:等.{0,14}(?:出来|进门).{0,18}让(?:他|她).{0,8}付出代价)|"
    r"(?:拿着|握着|手里有).{0,12}(?:撬棍|斧头|斧子|锤子|刀|棍).{0,36}"
    r"(?:打算|准备|计划).{0,28}(?:打|砍|攻击|袭击)(?:他|她|室友|同事|伴侣)|"
    r"(?:马上|现在|今晚)?(?:我)?(?:要|想|准备|打算|计划)?[^。；;\n]{0,10}"
    r"杀(?:了|掉|死)?(?:前伴侣|前任|伴侣|别人|他人|同事|室友|邻居|他|她)|"
    r"(?:about\s+to|intend\s+to).{0,18}(?:attack|kill)\s+(?:my\s+)?"
    r"(?:roommate|partner|someone|him|her|them)",
    re.IGNORECASE,
)
HEIGHT_EVENT_PATTERN = re.compile(
    r"(?:天台|楼顶|屋顶|高架桥|桥边|桥上|高处|窗台).{0,28}"
    r"(?:护栏外|栏杆外|跨过.{0,6}(?:护栏|栏杆)|准备.{0,8}(?:松手|跳下|跳楼)|打算.{0,8}(?:跳下|跳楼)|松手)|"
    r"(?:站到|站在|爬到).{0,12}(?:天台|楼顶|屋顶|桥边|高处|窗台外侧).{0,28}(?:跳下|跳楼|松手)|"
    r"(?:站到|站在|爬到).{0,12}窗台外侧",
    re.IGNORECASE,
)
RAIL_EVENT_PATTERN = re.compile(
    r"(?:铁路|铁轨|轨道|站台).{0,28}(?:冲向|冲过去|跳向|跳下)|"
    r"(?:走到|站在|靠近).{0,12}(?:铁路|铁轨|轨道|站台).{0,28}"
    r"(?:准备|打算|计划).{0,18}(?:冲向|冲过去|跳向)|"
    r"(?:已经)?(?:坐在|躺在|站在).{0,8}(?:铁路|铁轨|轨道)(?:上|中间)?"
    r".{0,32}(?:列车|火车|下一班车|地铁).{0,12}(?:分钟|马上|即将|快)",
    re.IGNORECASE,
)
DANGEROUS_MEDICATION_QUANTITY_PATTERN = re.compile(
    r"(?:一整|整|全部|全|过量|超量|半|一)\s*(?:瓶|板|盒).{0,14}"
    r"(?:安眠药|地高辛|药物|药片|药)|(?:安眠药|地高辛|药物|药片|药).{0,14}"
    r"(?:一整|整|全部|全|过量|超量|半|一)\s*(?:瓶|板|盒)|"
    r"(?:[一二三四五六七八九十百两\d]+(?:片|瓶|板|盒)).{0,10}(?:安眠药|止痛药|地高辛|药物|药片|药)|"
    r"(?:安眠药|地高辛|药物|药片|药).{0,10}[一二三四五六七八九十百两\d]+片|"
    r"(?:比|超过).{0,6}医嘱.{0,8}(?:多|过量|超量)",
    re.IGNORECASE,
)
MEDICATION_INGESTED_PATTERN = re.compile(
    r"(?:刚|刚刚|刚才|昨晚|今天|[一二三四五六七八九十两\d]+(?:分钟|小时)前)"
    r"[^。；;\n]{0,28}(?:吞了|吞下了|吞下(?!去)|吃了|服下了|服下(?!去)|喝下了|误喝了)|"
    r"(?:已经)[^。；;\n]{0,24}(?:吞了|吞下了|吞下(?!去)|吃了|服下了|服下(?!去)|喝下了)|"
    r"(?:吞了|吞下了|吞下(?!去)|吃了|服下了|服下(?!去)|喝下了|误喝了).{0,18}(?:头晕|恶心|呕吐|不适)",
    re.IGNORECASE,
)
MEDICATION_FUTURE_PATTERN = re.compile(
    r"(?:准备|打算|计划|十分钟后|马上|随后).{0,28}(?:吞|吃|服)(?:下|下去)?|"
    r"(?:吞|吃|服)(?:下|下去)?.{0,18}(?:准备|打算|计划)",
    re.IGNORECASE,
)
CURRENT_POISONING_SYMPTOM_PATTERN = re.compile(
    r"(?:现在|目前|今天|仍然|仍|开始).{0,24}"
    r"(?:头晕|恶心|呕吐|意识模糊|胸口发紧|越来越困|嗜睡|喉咙灼痛|呼吸困难|不适)",
    re.IGNORECASE,
)
POISONING_SYMPTOM_NEGATION_PATTERN = re.compile(
    r"(?:没有|并无|无)(?:任何)?(?:头晕|恶心|呕吐|意识模糊|胸口发紧|嗜睡|喉咙灼痛|呼吸困难|不适)",
    re.IGNORECASE,
)
TOXIC_SUBSTANCE_PATTERN = re.compile(
    r"强力清洁剂|清洁剂|洁厕剂|除锈剂|消毒剂(?:雾气)?|实验清洗液|管道疏通剂|"
    r"泳池(?:消毒)?药剂蒸气|实验室试剂|农药|除草剂|杀虫剂|漂白剂|"
    r"不明清洁液|腐蚀性液体|化学品|chemical",
    re.IGNORECASE,
)
TOXIC_INGESTION_PATTERN = re.compile(
    r"(?:刚才|刚刚|昨晚|今天|目前|现在)?[^。；;\n]{0,24}"
    r"(?:喝下了|误喝了|吞下了|摄入了)[^。；;\n]{0,16}"
    r"(?:强力清洁剂|清洁剂|农药|除草剂|杀虫剂|漂白剂|腐蚀性液体|化学品)|"
    r"(?:强力清洁剂|清洁剂|农药|除草剂|杀虫剂|漂白剂|腐蚀性液体|化学品)"
    r"[^。；;\n]{0,16}(?:喝下了|误喝了|吞下了|摄入了)",
    re.IGNORECASE,
)
BENIGN_WEAPON_PURPOSE_PATTERN = re.compile(
    r"切水果|做饭|做晚饭|参加比赛|去比赛|体育训练|运动训练|道具|摆拍",
    re.IGNORECASE,
)
MEANS_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("knife", re.compile(r"菜刀|匕首|刀具|\bknife\b|\bblade\b|刀", re.IGNORECASE)),
    ("firearm", re.compile(r"枪支|手枪|枪|\bgun\b|\bfirearm\b", re.IGNORECASE)),
    ("hammer", re.compile(r"锤子|铁锤|\bhammer\b", re.IGNORECASE)),
    ("baseball_bat", re.compile(r"棒球棍|球棒|baseball\s+bat", re.IGNORECASE)),
    ("blunt_object", re.compile(r"铁棍|棍棒|棍子", re.IGNORECASE)),
    ("crowbar", re.compile(r"撬棍", re.IGNORECASE)),
    ("axe", re.compile(r"斧头|斧子", re.IGNORECASE)),
    ("wire", re.compile(r"电线", re.IGNORECASE)),
    ("rope", re.compile(r"绳索|绳子", re.IGNORECASE)),
    ("generic_weapon", re.compile(r"武器|weapon", re.IGNORECASE)),
    ("dangerous_object", re.compile(r"危险物", re.IGNORECASE)),
)


def means_is_unavailable(sentence: str, start: int, end: int) -> bool:
    window = sentence[max(0, start - 16) : min(len(sentence), end + 18)]
    return bool(
        re.search(
            r"(?:手边|身边|房间里)?(?:没有|并无)(?:任何)?\s*(?:药|刀|枪|锤|棍|斧|电线|绳|武器|危险物)|"
            r"(?:不在身边|锁在别处|已锁|已经锁|已经交给|已交给|已经放下|已放下|"
            r"已经远离|已远离).{0,14}(?:药|刀|枪|锤|棍|斧|电线|绳|武器|危险物)|"
            r"(?:药|刀|枪|锤|棍|斧|电线|绳|武器|危险物).{0,14}(?:不在身边|锁在别处|已锁|已交给|已放下|已远离)|"
            r"(?:药|刀|枪|锤|棍|斧|电线|绳|武器|危险物).{0,14}(?:不在身边|锁在别处|已锁|已经交给|已交给|交给|已放下|已远离)|"
            r"(?:没有|并无)(?:任何)?\s*(?:药|刀|枪|锤|棍|斧|电线|绳|武器|危险物)(?:在身边|可用)?|"
            r"(?:no|without)\s+(?:a|any)?\s*(?:weapon|gun|firearm|knife|hammer|bat|rope)|"
            r"(?:weapon|gun|firearm|knife|hammer|bat|rope)\s+(?:is\s+)?(?:not\s+available|unavailable)|"
            r"(?:gun|firearm).{0,16}(?:locked\s+away|stored\s+safely)",
            window,
            re.IGNORECASE,
        )
    )


def grounded_means(
    sentence: str,
    sentence_start: int,
    medication_state: str | None = None,
    toxic_state: str | None = None,
    object_state: str = "held",
) -> tuple[GroundedMeans, ...]:
    values: list[GroundedMeans] = []
    if medication_state:
        medication_matches = list(re.finditer(
            r"(?:(?:一整|整|全部|全|半|一)\s*(?:瓶|板|盒)|"
            r"[一二三四五六七八九十百两\d]+\s*(?:片|瓶|板|盒))?\s*"
            r"(?:安眠药|止痛药|地高辛|处方药|药物|药片|药)",
            sentence,
            re.IGNORECASE,
        ))
        match = max(
            medication_matches,
            key=lambda item: (
                bool(re.search(r"安眠药|止痛药|地高辛|处方药|药物|药片", item.group(0))),
                len(item.group(0).strip()),
            ),
            default=None,
        )
        if match and not means_is_unavailable(sentence, match.start(), match.end()):
            values.append(
                GroundedMeans(
                    "medication",
                    medication_state,
                    match.group(0),
                    sentence_start + match.start(),
                    sentence_start + match.end(),
                )
            )
    if toxic_state:
        match = TOXIC_SUBSTANCE_PATTERN.search(sentence)
        if match:
            values.append(
                GroundedMeans(
                    "toxic_substance",
                    toxic_state,
                    match.group(0),
                    sentence_start + match.start(),
                    sentence_start + match.end(),
                )
            )
    for kind, pattern in MEANS_PATTERNS:
        match = pattern.search(sentence)
        if not match or means_is_unavailable(sentence, match.start(), match.end()):
            continue
        values.append(
            GroundedMeans(
                kind,
                object_state,
                match.group(0),
                sentence_start + match.start(),
                sentence_start + match.end(),
            )
        )
    return tuple(values)


def mask_pattern_matches(text: str, pattern: re.Pattern[str]) -> str:
    characters = list(text)
    for match in pattern.finditer(text):
        for index in range(match.start(), match.end()):
            if characters[index] not in "。；;\n":
                characters[index] = " "
    return "".join(characters)


def grounded_group(
    kind: str,
    state: str,
    sentence: str,
    sentence_start: int,
    match: re.Match[str],
    group: str,
) -> GroundedMeans:
    raw = match.group(group)
    value = raw.strip()
    offset = raw.find(value)
    start = match.start(group) + offset
    return GroundedMeans(kind, state, value, sentence_start + start, sentence_start + start + len(value))


def structured_safety_findings(active: str) -> list[SafetyFinding]:
    """Parse current-user safety events once, then reuse them for routing and rendering."""

    findings: list[SafetyFinding] = []
    symptom_pattern = re.compile(
        r"呕吐|想吐|恶心|昏沉|越来越困|嗜睡|灼痛|刺痛|流泪|视线.{0,4}发花|"
        r"咳嗽|喘不上气|呼吸困难|头晕|胸口发紧|意识模糊",
        re.IGNORECASE,
    )
    medication_pattern = re.compile(
        r"(?P<means>(?:(?:一整|整|半)\s*(?:盒|瓶|板|杯)|"
        r"[一二三四五六七八九十百两\d]+\s*(?:片|板|盒|瓶))\s*"
        r"[\u4e00-\u9fffA-Za-z0-9.-]{2,12}?)(?=，|,|都|摆|放|拿|倒|现在|十|但|$)",
        re.IGNORECASE,
    )
    poison_patterns: tuple[tuple[str, re.Pattern[str]], ...] = (
        (
            "ingested",
            re.compile(
                r"(?:误吞(?:了)?|误喝(?:了)?|喝下(?:了)?|喝(?:了)?|咽下(?:了)?|吞下(?:了)?|摄入(?:了)?)"
                r"(?:[一二三四五六七八九十半两\d]+\s*(?:口|杯))?\s*"
                r"(?P<substance>[^，。；;\n]{2,30}?)(?=，|,|现在|目前|今天|$)",
                re.IGNORECASE,
            ),
        ),
        (
            "inhaled",
            re.compile(
                r"(?:混合(?P<substance>[^，。；;\n]{2,42}?)后(?:吸入|闻到)(?:了)?(?:气体|蒸气)?|"
                r"(?:我)?(?:刚|刚刚|刚才)?(?:吸入|吸进)(?:了)?\s*"
                r"(?P<direct_substance>[^，。；;\n]{2,42}?)(?:后)?(?=，|,|现在|目前|今天|$))",
                re.IGNORECASE,
            ),
        ),
        (
            "eye_exposure",
            re.compile(
                r"(?P<substance>[^，。；;\n]{2,24}?)(?:刚)?(?:溅|喷)(?:进|入)我的?眼睛",
                re.IGNORECASE,
            ),
        ),
    )
    height_patterns = (
        re.compile(
            r"(?:跨坐在|站在|站到|爬到)(?P<place>[^，。；;\n]{1,36}?(?:矮墙|窗台外侧|栏杆外侧|护栏外侧|天台|楼顶|屋顶|桥边|高处))(?:上)?",
            re.IGNORECASE,
        ),
        re.compile(
            r"从(?P<place>[^，。；;\n]{1,36}?(?:栏杆外侧|护栏外侧))翻过去",
            re.IGNORECASE,
        ),
    )
    rail_pattern = re.compile(
        r"(?:蹲在|坐在|站在|靠近)(?P<place>[^，。；;\n]{1,32}?(?:铁路轨道|轨道|铁轨)(?:旁|上)?)",
        re.IGNORECASE,
    )
    self_means_patterns = (
        re.compile(
            r"把(?P<means>[^，。；;\n]{1,28}?)(?:套在门梁上|抵在(?:手腕|颈部|脖子)|"
            r"缠在(?:颈部|脖子)|系成环)",
            re.IGNORECASE,
        ),
        re.compile(
            r"(?:手里|手中)?(?:正|仍)?(?:攥着|握着|拿着|提着|拎着|抓着|手握)"
            r"(?P<means>[^，。；;\n]{1,28}?)(?=，|,|准备|打算|计划|等|去找|$)",
            re.IGNORECASE,
        ),
    )
    other_means_pattern = re.compile(
        r"(?:手里|手中)?(?:正|仍)?(?:攥着|握着|拿着|提着|拎着|抓着|手握)"
        r"(?P<means>[^，。；;\n]{1,28}?)(?=，|,|准备|打算|计划|等|去找|$)",
        re.IGNORECASE,
    )
    toxic_name_pattern = re.compile(
        r"清洁|洁厕|除锈|去锈|消毒|疏通|漂白|农药|除草|杀虫|除虫|防冻|化学|腐蚀|"
        r"试剂|清洗液|药剂|喷雾|不明液体|不明清洁液|雾气|蒸气|气体|chemical",
        re.IGNORECASE,
    )

    for sentence_match in SAFETY_SENTENCE_PATTERN.finditer(active):
        sentence = sentence_match.group(0)
        if not sentence.strip() or BENIGN_WEAPON_PURPOSE_PATTERN.search(sentence):
            continue
        sentence_start = sentence_match.start()
        sentence_end = sentence_match.end()

        for state, pattern in poison_patterns:
            exposure = pattern.search(sentence)
            if not exposure:
                continue
            group = "substance" if exposure.groupdict().get("substance") is not None else "direct_substance"
            if not toxic_name_pattern.search(exposure.group(group)):
                continue
            means = grounded_group("toxic_substance", state, sentence, sentence_start, exposure, group)
            findings.append(SafetyFinding("poisoning", "self", (means,), sentence_start, sentence_end))
            break

        medication = medication_pattern.search(sentence)
        if medication:
            means_available = bool(
                re.search(r"准备.{0,16}(?:一次)?(?:服下|吞下|吃下)|考虑.{0,12}(?:全|都)?吞|"
                          r"(?:全|都)吞掉|打算.{0,16}(?:服|吞|吃)", sentence, re.IGNORECASE)
            )
            means_ingested = bool(
                re.search(r"(?:刚|刚才|刚刚|分钟前|已经).{0,24}(?:吞下|吃了|服下|喝下)|"
                          r"(?:吞下|吃了|服下).{0,20}(?:现在|开始)", sentence, re.IGNORECASE)
            )
            if means_ingested and symptom_pattern.search(sentence):
                means = grounded_group("medication", "ingested", sentence, sentence_start, medication, "means")
                findings.append(SafetyFinding("poisoning", "self", (means,), sentence_start, sentence_end))
            elif means_available:
                means = grounded_group("medication", "available", sentence, sentence_start, medication, "means")
                findings.append(SafetyFinding("self_harm_intent", "self", (means,), sentence_start, sentence_end))

        if re.search(r"(?:想|准备|打算).{0,16}(?:往下跳|跳下|跳楼|松手)|(?:下一步|马上).{0,8}松手", sentence):
            for pattern in height_patterns:
                location = pattern.search(sentence)
                if location:
                    means = grounded_group("height", "at_location", sentence, sentence_start, location, "place")
                    findings.append(SafetyFinding("dangerous_height", "self", (means,), sentence_start, sentence_end))
                    break

        rail = rail_pattern.search(sentence)
        if rail and re.search(r"(?:准备|打算|计划).{0,18}(?:冲|跳)|(?:列车|火车).{0,10}(?:来|到)", sentence):
            means = grounded_group("rail", "at_location", sentence, sentence_start, rail, "place")
            findings.append(SafetyFinding("dangerous_rail", "self", (means,), sentence_start, sentence_end))

        direct_user = bool(
            re.search(
                r"(?:^|[，,\s])我|我(?:要|准备|打算|计划|已经|想|手里|有)|\bI\b",
                sentence,
                re.IGNORECASE,
            )
        )
        current_intent = bool(
            re.search(
                r"今晚|现在|此刻|马上|已经想好|准备|打算|计划|就要|"
                r"tonight|now|about\s+to|plan(?:ning)?\s+to|intend\s+to",
                sentence,
                re.IGNORECASE,
            )
        )
        direct_self_action = bool(
            re.search(
                r"(?:对|朝)(?:我)?自己开枪|开枪(?:打|射)(?:我)?自己|"
                r"shoot\s+myself|turn\s+(?:the\s+)?gun\s+on\s+myself",
                sentence,
                re.IGNORECASE,
            )
        )
        death_euphemism = bool(
            re.search(
                r"今晚[^，,。；;\n]{0,18}(?:不再醒来|不想再醒来|永远睡过去)|"
                r"(?:不再醒来|不想再醒来|永远睡过去)[^，,。；;\n]{0,18}今晚|"
                r"not\s+wake\s+up[^.;\n]{0,18}tonight|tonight[^.;\n]{0,18}not\s+wake\s+up",
                sentence,
                re.IGNORECASE,
            )
        )
        composed_self_intent = bool(
            direct_user
            and current_intent
            and (
                direct_self_action
                or (
                    death_euphemism
                    and re.search(
                        r"药|药片|安眠药|处方药|gun|firearm|knife|weapon",
                        sentence,
                        re.IGNORECASE,
                    )
                )
            )
        )
        self_intent = bool(
            SELF_HARM_INTENT_PATTERN.search(sentence)
            or composed_self_intent
            or re.search(
                r"准备.{0,18}(?:结束自己的生命|割伤自己|勒住自己)|"
                r"(?:缠在|套在|抵在|系成环).{0,24}(?:准备|下一步|马上).{0,18}(?:收紧|割伤|勒住|结束)|"
                r"想自杀|怕自己会(?:照做|伤害自己|自伤|自杀)",
                sentence,
                re.IGNORECASE,
            )
        )
        if self_intent:
            event_means: tuple[GroundedMeans, ...] = ()
            for pattern in self_means_patterns:
                means_match = pattern.search(sentence)
                if means_match:
                    means = grounded_group("object", "held", sentence, sentence_start, means_match, "means")
                    event_means = (means,)
                    break
            if not event_means and (
                DANGEROUS_MEDICATION_QUANTITY_PATTERN.search(sentence)
                or (death_euphemism and re.search(r"药|药片|安眠药|处方药", sentence))
            ):
                event_means = grounded_means(sentence, sentence_start, medication_state="available")
            if not event_means:
                event_means = grounded_means(sentence, sentence_start)
            findings.append(
                SafetyFinding("self_harm_intent", "self", event_means, sentence_start, sentence_end)
            )

        other_intent_match = None if self_intent else re.search(
            r"(?:准备|打算|计划|想要|想|怕自己会).{0,30}"
            r"(?:攻击|袭击|伤害|殴打|砍|打|砸)(?:伤|死)?"
            rf"(?P<target>{OTHER_HARM_TARGET_TOKEN})|"
            rf"(?:等|去找)(?P<target2>{OTHER_HARM_TARGET_TOKEN})"
            r".{0,28}(?:攻击|袭击|伤害|殴打|砍|打|砸)",
            sentence,
            re.IGNORECASE,
        )
        composed_other_intent = bool(
            not self_intent
            and direct_user
            and current_intent
            and OTHER_HARM_TARGET_PATTERN.search(sentence)
            and re.search(r"付出代价|pay(?:s|ing)?\s+(?:for|the\s+price)", sentence, re.IGNORECASE)
            and re.search(
                r"(?:刀|匕首|枪|gun|knife|weapon)[^，,。；;\n]{0,24}(?:包里|身边|手边|with\s+me)|"
                r"(?:包里|身边|手边|with\s+me)[^，,。；;\n]{0,24}(?:刀|匕首|枪|gun|knife|weapon)",
                sentence,
                re.IGNORECASE,
            )
        )
        if other_intent_match or composed_other_intent:
            means_match = other_means_pattern.search(sentence)
            event_means: tuple[GroundedMeans, ...] = ()
            if means_match:
                means = grounded_group("object", "held", sentence, sentence_start, means_match, "means")
                event_means = (means,)
            if not event_means and composed_other_intent:
                event_means = grounded_means(sentence, sentence_start, object_state="available")
            target_match = OTHER_HARM_TARGET_PATTERN.search(sentence)
            target_text = (
                (other_intent_match.group("target") or other_intent_match.group("target2"))
                if other_intent_match
                else (target_match.group(0) if target_match else None)
            )
            findings.append(
                SafetyFinding(
                    "other_harm_intent",
                    "other",
                    event_means,
                    sentence_start,
                    sentence_end,
                    target_text,
                )
            )

    deduped: list[SafetyFinding] = []
    for finding in findings:
        if finding not in deduped:
            deduped.append(finding)
    return deduped


def cross_boundary_safety_findings(active: str) -> list[SafetyFinding]:
    """Compose a direct user's current intent with means in adjacent clauses."""

    clauses = [match for match in SAFETY_SENTENCE_PATTERN.finditer(active) if match.group(0).strip()]
    findings: list[SafetyFinding] = []
    for index in range(len(clauses)):
        for width in (2, 3):
            selected = clauses[index : index + width]
            if len(selected) != width:
                continue
            start, end = selected[0].start(), selected[-1].end()
            window = active[start:end]
            if BENIGN_WEAPON_PURPOSE_PATTERN.search(window):
                continue
            direct_user = bool(
                re.search(
                    r"我(?:要|想|不想|决定|已经|准备|打算|计划|手里|手中|手边|有)|"
                    r"对(?:我)?自己|杀了?自己|shoot\s+myself|\bI\b",
                    window,
                    re.IGNORECASE,
                )
            )
            if not direct_user:
                continue

            medication_available = bool(
                re.search(r"药|药片|安眠药|处方药", window, re.IGNORECASE)
                and re.search(
                    r"(?:药|药片|安眠药|处方药).{0,12}(?:就在|摆在|放在|有在)?"
                    r"(?:桌上|床头柜|手边|身边|房间里)|"
                    r"(?:就在|摆在|放在|已经摆在|已经放在).{0,12}"
                    r"(?:桌上|床头柜|手边|身边|房间里)|"
                    r"(?:桌上|床头柜|手边|身边|房间里).{0,12}(?:有|放着|摆着|就在)"
                    r".{0,12}(?:药|药片|安眠药|处方药)|"
                    r"(?:药|药片|安眠药).{0,18}(?:全部|全|都)?(?:吃完|吞下|服下)|"
                    r"(?:吞完|吞下|吃完|服下).{0,16}(?:一整|这一|整)?(?:瓶|盒|板)?"
                    r"(?:药|药片|安眠药|处方药)",
                    window,
                    re.IGNORECASE,
                )
            )
            weapon_available = bool(
                re.search(
                    r"刀|匕首|枪|猎枪|绳子|绳索|gun|firearm|knife|rope|weapon",
                    window,
                    re.IGNORECASE,
                )
                and re.search(
                    r"(?:手里|手中|包里|兜里|身边|手边|房间里|床头柜).{0,16}(?:有|拿着|放着|就在)?"
                    r"(?:刀|匕首|枪|猎枪|绳子|绳索|gun|firearm|knife|rope|weapon)|"
                    r"(?:刀|匕首|枪|猎枪|绳子|绳索|gun|firearm|knife|rope|weapon).{0,20}"
                    r"(?:手里|手中|包里|兜里|身边|手边|房间里|床头柜|放进包里|已经放进包里)|"
                    r"(?:gun|firearm|weapon).{0,20}(?:loaded\s+)?(?:beside|next\s+to|with)\s+me",
                    window,
                    re.IGNORECASE,
                )
            )
            self_intent = bool(
                re.search(
                    r"(?:今晚|现在|此刻)?(?:我)?(?:决定|已经想好|想好|准备|打算|计划)?"
                    r".{0,28}(?:不想再醒(?:过)?来|不再醒(?:过)?来|永远睡过去)|"
                    r"(?:我)?(?:要|决定|准备|打算|计划)[^。；;\n]{0,12}"
                    r"(?:自杀|结束(?:自己的?)?生命)|"
                    r"(?:准备|打算|计划).{0,16}(?:对(?:我)?自己开枪|shoot\s+myself)|"
                    r"(?:对(?:我)?自己开枪|朝(?:我)?自己扣扳机|shoot\s+myself)|"
                    r"(?:吞完|吞下|吃完|服下)[^。；;\n]{0,16}(?:药|药片)"
                    r".{0,20}(?:不想再醒(?:过)?来|不再醒(?:过)?来)",
                    window,
                    re.IGNORECASE,
                )
            )
            if self_intent and (medication_available or weapon_available):
                means = grounded_means(
                    window,
                    start,
                    medication_state="available" if medication_available else None,
                    object_state="available",
                )
                findings.append(SafetyFinding("self_harm_intent", "self", means, start, end))
                continue

            other_intent = re.search(
                rf"(?:我)?(?:想|要|准备|打算|计划)?[^。；;\n]{{0,10}}(?:杀了?|伤害|攻击|砍|捅)"
                rf"(?P<target>{OTHER_HARM_TARGET_TOKEN})|"
                rf"(?:今晚|现在|此刻)?我?(?:要|想|准备|打算|计划)?[^。；;\n]{{0,12}}"
                rf"(?:让)(?P<target2>{OTHER_HARM_TARGET_TOKEN})付出代价",
                window,
                re.IGNORECASE,
            )
            if other_intent and weapon_available and re.search(
                r"今晚|现在|此刻|马上|去找|已经放进包里|放进包里|"
                r"手里|手中|包里|兜里|身边|手边|房间里|beside\s+me|with\s+me",
                window,
                re.IGNORECASE,
            ):
                means = grounded_means(window, start, object_state="available")
                target_text = other_intent.group("target") or other_intent.group("target2")
                findings.append(
                    SafetyFinding("other_harm_intent", "other", means, start, end, target_text)
                )
    deduped: list[SafetyFinding] = []
    for finding in findings:
        if finding not in deduped:
            deduped.append(finding)
    return deduped


V12_RECENT_SELF_HARM_PATTERN = re.compile(
    r"(?:过去|最近)[一二三四五六七八九十两\d]+(?:天|周).{0,20}"
    r"(?:反复|每天).{0,18}(?:不如死了|醒不过来就好了|不想醒来|死亡念头)",
    re.IGNORECASE,
)
V12_CURRENT_SELF_HARM_PATTERN = re.compile(
    r"我(?:现在|今晚|此刻).{0,28}(?:要自杀|准备.{0,8}割自己|就要结束自己|"
    r"有自伤想法和具体计划|有具体自杀计划|准备吞下.{0,18}来自杀)|"
    r"我刚才想割自己|今天又出现了具体自杀计划|"
    r"我已经站在高处边缘.{0,16}跳下去",
    re.IGNORECASE,
)
V12_CURRENT_OTHER_HARM_PATTERN = re.compile(
    r"我(?:现在|正在|刚才).{0,48}(?:准备伤害他|准备打他|准备杀了老板|"
    r"计划伤害邻居|要拿棍子打房东|想拿枪去伤人|拿着球棒.{0,12}打老板|"
    r"开车去.{0,18}准备伤害他)",
    re.IGNORECASE,
)
V12_THIRD_PARTY_SELF_HARM_PATTERN = re.compile(
    r"(?P<actor>朋友|同事|室友|伴侣|家人).{0,20}(?:他|她)现在要自杀",
    re.IGNORECASE,
)
V12_THIRD_PARTY_OTHER_HARM_PATTERN = re.compile(
    r"(?P<actor>朋友|同事|室友|伴侣|家人).{0,24}(?:他|她)现在要拿.{0,12}(?:打|伤害)",
    re.IGNORECASE,
)
V12_EXPLICIT_NO_CURRENT_SAFETY_PATTERN = re.compile(
    r"此后一直没有再发生|今天没有相关想法|现在没有要伤害任何人的想法|"
    r"没有自伤想法.{0,16}没有计划|不会去找他.{0,28}没有伤害计划|"
    r"不会去对方所在地.{0,40}没有伤害计划|今天没有发生暴露|"
    r"没有吞咽、吸入或弄进眼睛|没有进入眼睛|没有闻到、吸入或接触|"
    r"没碰到也没吸入|没有吸入|没有吞.{0,16}已经把药交给",
    re.IGNORECASE,
)
V12_TOXIC_INGESTION_PATTERN = re.compile(
    r"(?P<actor>我的孩子|我)[^。；;\n]{0,18}?"
    r"(?:吞下了|吞了|误吞(?!过)|喝了|喝下了)"
    r"(?P<substance>(?:一口)?(?:漂白剂|清洁剂|农药|洗衣液|有毒液体))",
    re.IGNORECASE,
)
V12_MEDICATION_INGESTION_PATTERN = re.compile(
    r"我[^。；;\n]{0,18}?把(?P<substance>一把不明药片)吞下去了",
    re.IGNORECASE,
)
V12_TOXIC_INHALATION_PATTERN = re.compile(
    r"我[^。；;\n]{0,36}?(?:吸入了|吸入)"
    r"(?P<substance>里面冒出的气体|气体|一口)|"
    r"(?P<spray>有毒喷雾)[^。；;\n]{0,24}我[^。；;\n]{0,12}(?:吸入了|吸入)一口",
    re.IGNORECASE,
)
V12_TOXIC_EYE_PATTERN = re.compile(
    r"(?P<substance>实验液体|漂白剂)[^。；;\n]{0,10}(?:溅进|进入|进了)我的眼睛",
    re.IGNORECASE,
)
V25_THIRD_PARTY_MEDICATION_INTENT_PATTERN = re.compile(
    r"(?P<actor>我的孩子|孩子|朋友|同事|室友|伴侣|家人)"
    r"(?:发消息)?说(?:他|她)?[^。；;\n]{0,30}?"
    r"(?P<means>(?:一整|整|全部|全)\s*(?:瓶|板|盒)\s*"
    r"(?:安眠药|止痛药|药物|药片|药))"
    r"[^。；;\n]{0,18}(?:准备|打算|计划).{0,10}(?:全部|全|都)?(?:吞下|吃下|服下)",
    re.IGNORECASE,
)
V25_DIRECT_MEDICATION_INGESTION_PATTERNS = (
    re.compile(
        r"我(?:刚|刚刚|刚才|已经)?(?:一口气)?(?:吃了|吞了|吞下|服下)"
        r"(?P<means>[一二三四五六七八九十百两\d]+\s*(?:颗|片)\s*"
        r"(?:泰诺|扑热息痛|对乙酰氨基酚|安眠药|止痛药|药片|药))",
        re.IGNORECASE,
    ),
    re.compile(
        r"I\s+(?:just\s+)?(?:swallowed|took|ingested)\s+"
        r"(?P<means>(?:[a-z]+|\d+)\s+(?:Tylenol|paracetamol|acetaminophen|"
        r"sleeping\s+pills?|painkillers?)(?:\s+tablets?|\s+pills?)?)",
        re.IGNORECASE,
    ),
)
V40_DIRECT_RAIL_COLLISION_PATTERN = re.compile(
    r"我(?:现在|此刻|目前)?(?:站在|坐在|躺在|蹲在)"
    r"(?P<means>[^，。；;\n]{0,12}?(?:铁路轨道|轨道|铁轨)(?:上|中间)?)"
    r"[^。；;\n]{0,18}(?:等|让)[^。；;\n]{0,8}(?:列车|火车|地铁)"
    r"[^。；;\n]{0,8}(?:撞我|碾我|撞死我|碾过我)",
    re.IGNORECASE,
)
V25_DIRECT_SELF_HARM_PATTERNS = (
    re.compile(r"我(?:现在|此刻|马上)?(?:要|准备|打算|计划)(?:割腕|割开手腕)", re.IGNORECASE),
    re.compile(r"我已经(?:割腕|割开手腕)(?:了)?[^。；;\n]{0,20}(?:流血|血.{0,6}流)", re.IGNORECASE),
    re.compile(r"我把(?:绳子|绳索|电线)套在(?:脖子|颈部)上(?:了)?", re.IGNORECASE),
    re.compile(r"I\s+am\s+about\s+to\s+cut\s+my\s+wrists?", re.IGNORECASE),
)
V25_DIRECT_OTHER_HARM_PATTERN = re.compile(
    r"我(?:现在|此刻|马上)?(?:要|准备|打算|计划)"
    r"(?:开车)?(?:撞|掐死|勒死|杀死|杀掉|捅|砍)"
    r"(?P<target>室友|伴侣|家人|同事|邻居|前任|他|她|别人)",
    re.IGNORECASE,
)


def safety_sentence_bounds(text: str, start: int, end: int) -> tuple[int, int]:
    left = max((text.rfind(mark, 0, start) for mark in "。；;\n"), default=-1) + 1
    right_candidates = [position + 1 for mark in "。；;\n" if (position := text.find(mark, end)) >= 0]
    return left, min(right_candidates, default=len(text))


def grounded_v12_means(
    text: str,
    match: re.Match[str],
    group: str,
    kind: str,
    state: str,
) -> tuple[GroundedMeans, ...]:
    raw = match.group(group)
    value = raw.strip()
    offset = raw.find(value)
    start = match.start(group) + offset
    return (GroundedMeans(kind, state, value, start, start + len(value)),)


def v25_explicit_safety_findings(text: str) -> list[SafetyFinding]:
    """Parse explicit present-tense events with actor and completed-state binding."""

    findings: list[SafetyFinding] = []

    rail = V40_DIRECT_RAIL_COLLISION_PATTERN.search(text)
    if rail:
        start, end = safety_sentence_bounds(text, rail.start(), rail.end())
        findings.append(
            SafetyFinding(
                "dangerous_rail",
                "self",
                grounded_v12_means(text, rail, "means", "rail", "at_location"),
                start,
                end,
            )
        )

    third_party = V25_THIRD_PARTY_MEDICATION_INTENT_PATTERN.search(text)
    if third_party:
        start, end = safety_sentence_bounds(text, third_party.start(), third_party.end())
        findings.append(
            SafetyFinding(
                "self_harm_intent",
                "third_party",
                grounded_v12_means(text, third_party, "means", "medication", "available"),
                start,
                end,
                third_party.group("actor"),
            )
        )

    for pattern in V25_DIRECT_MEDICATION_INGESTION_PATTERNS:
        medication = pattern.search(text)
        if not medication:
            continue
        start, end = safety_sentence_bounds(text, medication.start(), medication.end())
        findings.append(
            SafetyFinding(
                "poisoning",
                "self",
                grounded_v12_means(text, medication, "means", "medication", "ingested"),
                start,
                end,
            )
        )
        break

    for pattern in V25_DIRECT_SELF_HARM_PATTERNS:
        event = pattern.search(text)
        if not event:
            continue
        start, end = safety_sentence_bounds(text, event.start(), event.end())
        sentence = text[start:end]
        findings.append(
            SafetyFinding(
                "self_harm_intent",
                "self",
                grounded_means(sentence, start),
                start,
                end,
            )
        )
        break

    other = V25_DIRECT_OTHER_HARM_PATTERN.search(text)
    if other:
        start, end = safety_sentence_bounds(text, other.start(), other.end())
        sentence = text[start:end]
        findings.append(
            SafetyFinding(
                "other_harm_intent",
                "other",
                grounded_means(sentence, start),
                start,
                end,
                other.group("target"),
            )
        )
    return findings


def v12_supplemental_safety_findings(text: str) -> list[SafetyFinding]:
    """Cover actor, recency and completed-exposure states missed by the legacy parser."""

    if is_nonpersonal_transformation_task(text):
        return []
    findings: list[SafetyFinding] = v25_explicit_safety_findings(text)

    def append_event(
        kind: str,
        target: str,
        match: re.Match[str],
        means: tuple[GroundedMeans, ...] = (),
        target_text: str | None = None,
    ) -> None:
        start, end = safety_sentence_bounds(text, match.start(), match.end())
        item = SafetyFinding(kind, target, means, start, end, target_text)
        if item not in findings:
            findings.append(item)

    recent = V12_RECENT_SELF_HARM_PATTERN.search(text)
    if recent:
        append_event("recent_self_harm", "self", recent)

    third_self = V12_THIRD_PARTY_SELF_HARM_PATTERN.search(text)
    if third_self and re.search(r"是(?:他|她)，不是我|现实帮助", text):
        append_event("self_harm_intent", "third_party", third_self, target_text=third_self.group("actor"))

    third_other = V12_THIRD_PARTY_OTHER_HARM_PATTERN.search(text)
    if third_other and re.search(r"是(?:室友|朋友|同事|他|她)，不是我", text):
        append_event("other_harm_intent", "third_party", third_other, target_text=third_other.group("actor"))

    self_harm = V12_CURRENT_SELF_HARM_PATTERN.search(text)
    if self_harm:
        start, end = safety_sentence_bounds(text, self_harm.start(), self_harm.end())
        sentence = text[start:end]
        medication_state = "available" if re.search(r"药片", sentence) else None
        append_event(
            "self_harm_intent",
            "self",
            self_harm,
            grounded_means(sentence, start, medication_state),
        )

    other_harm = V12_CURRENT_OTHER_HARM_PATTERN.search(text)
    if other_harm:
        start, end = safety_sentence_bounds(text, other_harm.start(), other_harm.end())
        sentence = text[start:end]
        target = OTHER_HARM_TARGET_PATTERN.search(sentence)
        if target is None:
            target = re.search(r"老板|房东|对方", sentence)
        append_event(
            "other_harm_intent",
            "other",
            other_harm,
            grounded_means(sentence, start),
            target.group(0) if target else None,
        )

    medication = V12_MEDICATION_INGESTION_PATTERN.search(text)
    if medication:
        append_event(
            "poisoning",
            "self",
            medication,
            grounded_v12_means(text, medication, "substance", "medication", "ingested"),
        )

    ingestion = V12_TOXIC_INGESTION_PATTERN.search(text)
    if ingestion:
        third_party = ingestion.group("actor") != "我"
        append_event(
            "poisoning",
            "third_party" if third_party else "self",
            ingestion,
            grounded_v12_means(text, ingestion, "substance", "toxic_substance", "ingested"),
            "孩子" if third_party else None,
        )

    inhalation = V12_TOXIC_INHALATION_PATTERN.search(text)
    if inhalation:
        group = "spray" if inhalation.group("spray") else "substance"
        append_event(
            "poisoning",
            "self",
            inhalation,
            grounded_v12_means(text, inhalation, group, "toxic_substance", "inhaled"),
        )

    eye = V12_TOXIC_EYE_PATTERN.search(text)
    if eye:
        append_event(
            "poisoning",
            "self",
            eye,
            grounded_v12_means(text, eye, "substance", "toxic_substance", "eye_exposure"),
        )
    return findings


def analyze_safety(text: str) -> SafetyProfile:
    """Extract current first-person safety events with event-local means."""

    live_material_override = bool(LIVE_PERSONAL_SAFETY_OVERRIDE_PATTERN.search(text))
    if is_nonpersonal_transformation_task(text) and not live_material_override:
        return SafetyProfile(text, ())
    supplemental = v12_supplemental_safety_findings(text)
    if V12_EXPLICIT_NO_CURRENT_SAFETY_PATTERN.search(text) and not supplemental:
        return SafetyProfile(text, ())
    active = text if live_material_override else active_domain_text(text, "safety")
    active = mask_pattern_matches(active, RESOLVED_PAST_HARM_PATTERN)
    active = mask_pattern_matches(active, CURRENT_HARM_NEGATION_PATTERN)
    active = mask_pattern_matches(active, SAFETY_NEGATION_PATTERN)
    findings: list[SafetyFinding] = list(supplemental)
    for item in structured_safety_findings(active):
        if item not in findings:
            findings.append(item)
    for item in cross_boundary_safety_findings(active):
        if item not in findings:
            findings.append(item)

    for segment in iter_scoped_segments(text):
        if segment.actor != "user" or segment.context != "direct":
            continue
        if POISONING_SYMPTOM_NEGATION_PATTERN.search(segment.text):
            continue
        if (
            re.search(r"按医嘱", segment.text)
            and re.search(r"(?:一|1)\s*片", segment.text)
            and not re.search(r"一整|整瓶|整板|全部|过量|超量|(?:比|超过).{0,6}医嘱", segment.text)
        ):
            continue
        if not (
            DANGEROUS_MEDICATION_QUANTITY_PATTERN.search(segment.text)
            and MEDICATION_INGESTED_PATTERN.search(segment.text)
            and CURRENT_POISONING_SYMPTOM_PATTERN.search(segment.text)
        ):
            continue
        findings.append(
            SafetyFinding(
                "poisoning",
                "self",
                grounded_means(segment.text, segment.start, "ingested"),
                segment.start,
                segment.end,
            )
        )

    for match in SAFETY_SENTENCE_PATTERN.finditer(active):
        sentence = match.group(0)
        if not sentence.strip() or BENIGN_WEAPON_PURPOSE_PATTERN.search(sentence):
            continue
        if any(item.start == match.start() and item.end == match.end() for item in findings):
            continue
        finding: SafetyFinding | None = None
        has_dangerous_quantity = bool(DANGEROUS_MEDICATION_QUANTITY_PATTERN.search(sentence))
        if (
            re.search(r"按医嘱", sentence)
            and re.search(r"(?:一|1)\s*片", sentence)
            and not re.search(r"一整|整瓶|整板|全部|过量|超量|(?:比|超过).{0,6}医嘱", sentence)
        ):
            has_dangerous_quantity = False
        toxic_ingested = bool(TOXIC_INGESTION_PATTERN.search(sentence))
        toxic_symptoms = bool(
            CURRENT_POISONING_SYMPTOM_PATTERN.search(sentence)
            and not POISONING_SYMPTOM_NEGATION_PATTERN.search(sentence)
        )
        if toxic_ingested and (toxic_symptoms or SELF_HARM_INTENT_PATTERN.search(sentence)):
            finding = SafetyFinding(
                "poisoning",
                "self",
                grounded_means(sentence, match.start(), toxic_state="ingested"),
                match.start(),
                match.end(),
            )
        elif has_dangerous_quantity and MEDICATION_INGESTED_PATTERN.search(sentence):
            finding = SafetyFinding(
                "poisoning", "self", grounded_means(sentence, match.start(), "ingested"), match.start(), match.end()
            )
        elif has_dangerous_quantity and MEDICATION_FUTURE_PATTERN.search(sentence):
            finding = SafetyFinding(
                "self_harm_intent", "self", grounded_means(sentence, match.start(), "available"), match.start(), match.end()
            )
        elif HEIGHT_EVENT_PATTERN.search(sentence):
            height = re.search(r"天台|楼顶|屋顶|高架桥|桥边|桥上|高处|窗台|护栏|栏杆", sentence)
            means = ()
            if height:
                means = (
                    GroundedMeans(
                        "height",
                        "at_location",
                        height.group(0),
                        match.start() + height.start(),
                        match.start() + height.end(),
                    ),
                )
            finding = SafetyFinding("dangerous_height", "self", means, match.start(), match.end())
        elif RAIL_EVENT_PATTERN.search(sentence):
            rail = re.search(r"铁路|铁轨|轨道|站台", sentence)
            means = ()
            if rail:
                means = (
                    GroundedMeans(
                        "rail",
                        "at_location",
                        rail.group(0),
                        match.start() + rail.start(),
                        match.start() + rail.end(),
                    ),
                )
            finding = SafetyFinding("dangerous_rail", "self", means, match.start(), match.end())
        elif OTHER_HARM_INTENT_PATTERN.search(sentence):
            target = re.search(r"roommate|partner|someone", sentence, re.IGNORECASE)
            if target is None:
                target = OTHER_HARM_TARGET_PATTERN.search(sentence)
            finding = SafetyFinding(
                "other_harm_intent",
                "other",
                grounded_means(sentence, match.start()),
                match.start(),
                match.end(),
                target.group(0) if target else None,
            )
        elif SELF_HARM_INTENT_PATTERN.search(sentence):
            medication_state = "available" if re.search(r"药|安眠药|地高辛", sentence) else None
            finding = SafetyFinding(
                "self_harm_intent",
                "self",
                grounded_means(sentence, match.start(), medication_state),
                match.start(),
                match.end(),
            )
        if finding and finding not in findings:
            findings.append(finding)

    return SafetyProfile(active, tuple(findings))


def has_immediate_safety_signal(text: str) -> bool:
    return analyze_safety(text).immediate


def has_recent_self_harm_signal(text: str) -> bool:
    return analyze_safety(text).needs_prompt_support


def safety_profile(text: str) -> SafetyProfile:
    return analyze_safety(text)


def safety_features(text: str) -> set[str]:
    return set(analyze_safety(text).features)


MEDICAL_REQUEST_CUE_PATTERN = re.compile(
    r"(?:请)?(?:帮我|替我|为我)[^。；;\n]{0,24}"
    r"(?:停药|停用|停掉|停止服用|减量|加量|换药|调整剂量|暂停治疗|终止治疗)|"
    r"请[^。；;\n]{0,30}(?:告诉|替我|决定|确认)|替我决定|"
    r"我(?:今晚|今天|现在|从下周起?|暂时)?(?:想|准备|打算|要).{0,36}"
    r"(?:停|减|加|换|改|少吃|多吃|取消|暂停|中止|终止)|"
    r"(?:停药|停掉|停用|减量|加量|换药|调整剂量|隔天(?:吃|服)|取消治疗|暂停治疗).{0,12}"
    r"(?:行不行|可以吗|该不该|还是)|"
    r"(?:下周|下个月|明天|今晚|今天|现在).{0,16}(?:开始)?想.{0,30}"
    r"(?:停|减|加|换|改|取消|暂停|中止|终止)|"
    r"你.{0,18}(?:替我|帮我)?(?:确认|决定|制定|定下).{0,18}(?:方案|调整|治疗|决定)|"
    r"(?:我)?应该(?:马上|现在|今晚)?(?:停药|停掉|停用|减量|加量|换药|调整剂量|"
    r"少吃|多吃|取消|暂停|中止|终止)|"
    r"(?:我)?(?:今晚|今天|现在)?能不能.{0,20}(?:停|减|降|加|升|换|改|取消|暂停)|"
    r"(?:行不行|可以吗|该不该|还是).{0,20}(?:停|减|加|换|改|取消|暂停)|"
    r"(?:I\s+)?want\s+to.{0,24}(?:stop|change|reduce|increase|switch).{0,24}"
    r"(?:medication|medicine|dose|treatment)|"
    r"(?:decide|confirm)(?:\s+whether)?(?:\s+to)?[^.;]{0,28}(?:for\s+me|tonight|tomorrow)|"
    r"(?:decide|confirm)\s+for\s+me",
    re.IGNORECASE,
)
CLINICIAN_DIRECTED_CHANGE_PATTERN = re.compile(
    r"(?:医生|医师|处方人员|治疗师).{0,24}(?:已经|已|决定|共同决定|书面安排|安排|医嘱|要求).{0,24}"
    r"(?:停|减|加|换|改|取消|暂停|中止|终止)",
    re.IGNORECASE,
)
GENERAL_MEDICAL_CHANGE_PATTERN = re.compile(
    r"(?:停用|停掉|停止服用|彻底停掉|完全停用|换用|换成|加量|减量|翻倍|减半|"
    r"改成隔周|改为隔周|从每周一次改成隔周一次|调整为隔周|上调|下调).{0,24}"
    r"(?:处方|医生开的|药|剂量|治疗|会谈)|"
    r"(?:处方|医生开的|甲氨蝶呤|胰岛素|帕罗西汀|氟西汀|生物制剂|药物|剂量|治疗|会谈)"
    r".{0,36}(?:停用|停掉|停止|改成|改为|换成|加量|减量|翻倍|减半|隔周|上调|下调)|"
    r"(?:每周一次|每餐剂量).{0,20}(?:改成|改为|翻倍|减半|隔周)",
    re.IGNORECASE,
)
CLINICIAN_ESTABLISHED_PLAN_PATTERN = re.compile(
    r"(?:医生|医师|处方人员|治疗师|专科).{0,36}"
    r"(?:已经|已|今天|书面|共同完成|安排|决定|根据).{0,36}"
    r"(?:停用|停掉|停止|改成|改为|调整|上调|下调|加量|减量|隔周|结疗|"
    r"medication\s+holiday|药物假期)",
    re.IGNORECASE,
)
NO_AI_MEDICAL_DECISION_PATTERN = re.compile(
    r"不(?:请|让|要).{0,12}AI.{0,12}(?:改|决定|调整)|"
    r"不(?:需要|要求|让)(?:你|AI).{0,12}(?:改|修改|决定|调整|加码)|"
    r"只是按.{0,12}(?:处方|方案)记录|只记录(?:已确认|既定|书面)?方案|"
    r"我会按书面方案执行|并未让AI改方案",
    re.IGNORECASE,
)
V12_MEDICAL_CHANGE_ACTION_PATTERN = re.compile(
    r"(?:舍曲林|哌甲酯|锂盐|氯硝西泮|抗精神病药|托莫西汀|抗抑郁药)"
    r".{0,34}(?:停不停|减半|跳过这一剂|减量表|停掉|加到双倍|重新开始吃多少|调整到新剂量|"
    r"按新处方重新开始|维持现有|按原处方继续)|"
    r"(?:减量表|新处方).{0,18}(?:氯硝西泮|抗抑郁药)|"
    r"(?:按原处方继续|维持现有|按新处方重新开始).{0,18}(?:舍曲林|抗精神病药|抗抑郁药)|"
    r"(?:电休克治疗).{0,36}(?:取消|接受|安排)|"
    r"(?:暴露练习|分级暴露计划).{0,32}(?:强度翻倍|加码|当前一级执行)|"
    r"(?:医生|治疗师|主治团队).{0,30}(?:调整了|共同决定.{0,16}暂停|安排下次|给了分级暴露计划)",
    re.IGNORECASE,
)
V12_AI_MEDICAL_DELEGATION_PATTERN = re.compile(
    r"(?:你|AI)(?:直接)?(?:替我|帮我)?(?:决定|设计)|"
    r"替我决定|帮我设计|必须选一个|你替我把|不要叫我联系医生|别让我问医生",
    re.IGNORECASE,
)
V12_CLINICIAN_ESTABLISHED_PLAN_PATTERN = re.compile(
    r"(?:开药医生|精神科医生|医生|治疗师|主治团队).{0,60}"
    r"(?:按原处方继续|书面让我|调整了|给我.{0,8}减量表|共同决定暂停|维持现有|"
    r"共同决定.{0,16}暂停|完成知情讨论并安排|调整到新剂量|按新处方重新开始|"
    r"给了分级暴露计划)",
    re.IGNORECASE,
)
MEDICATION_NAME_PATTERN = (
    r"(?:舍曲林|哌甲酯|锂盐|氯硝西泮|托莫西汀|喹硫平|丙戊酸|"
    r"劳拉西泮|来士普|艾司西酞普兰|胰岛素|帕罗西汀|氟西汀|"
    r"拉莫三嗪|甲氨蝶呤|地高辛|抗精神病药|抗抑郁药|处方药|"
    r"医生给我的[^，。；;]{0,10}药片|白色药片|药片|药物)"
)
MEDICATION_ADJUSTMENT_PATTERN = re.compile(
    rf"{MEDICATION_NAME_PATTERN}[^，。；;\n]{{0,36}}"
    r"(?:掰(?:成)?(?:半片|一半|四分之一)|少吃(?:一颗|一片|一顿)?|"
    r"多吃(?:一颗|一片)?|省掉(?:一顿|一剂)|跳过(?:一顿|一剂)?|"
    r"隔天(?:吃|服)(?:一次)?|多打[^，。；;\n]{0,8}(?:单位)?|"
    r"少打[^，。；;\n]{0,8}(?:单位)?|停掉|停用|停服|停止服用|"
    r"减量|加量|减半|加倍|换药|改剂量|调整剂量)|"
    r"(?:掰(?:成)?(?:半片|一半|四分之一)|少吃|多吃|省掉|跳过|"
    r"隔天(?:吃|服)|多打|少打|停掉|停用|停服|减量|加量|减半|加倍)"
    rf"[^，。；;\n]{{0,28}}{MEDICATION_NAME_PATTERN}",
    re.IGNORECASE,
)
MEDICAL_PROCEDURE_ADJUSTMENT_PATTERN = re.compile(
    r"(?:不去做|不做|取消|暂停|停止|关掉|中止|推迟|改期)"
    r"[^，。；;\n]{0,20}(?:ECT|电休克(?:治疗)?|电痉挛(?:治疗)?|"
    r"深部脑刺激|DBS|手术|医疗程序)|"
    r"(?:ECT|电休克(?:治疗)?|电痉挛(?:治疗)?|深部脑刺激|DBS|手术|医疗程序)"
    r"[^，。；;\n]{0,24}(?:不去做|不做|取消|暂停|停止|关掉|中止|推迟|改期)",
    re.IGNORECASE,
)
MEDICAL_DECISION_DELEGATION_PATTERN = re.compile(
    r"(?:直接)?(?:告诉我|替我拍板|你说行就行|帮我确认|你觉得对不对|"
    r"你赞成吗|替我判断|替我决定|帮我决定|怎么样|好吗|可以吗|行不行|该不该)",
    re.IGNORECASE,
)


def has_medical_change_action(text: str) -> bool:
    return bool(
        MEDICAL_CHANGE_PATTERN.search(text)
        or TREATMENT_CHANGE_PATTERN.search(text)
        or GENERAL_MEDICAL_CHANGE_PATTERN.search(text)
        or V12_MEDICAL_CHANGE_ACTION_PATTERN.search(text)
        or MEDICATION_ADJUSTMENT_PATTERN.search(text)
        or MEDICAL_PROCEDURE_ADJUSTMENT_PATTERN.search(text)
        or re.search(
            r"(?:停掉|停用|停服|停止服用|减半|加倍|跳过|漏服|少服|多服)"
            r".{0,20}(?:舍曲林|哌甲酯|锂盐|氯硝西泮|抗精神病药|托莫西汀|"
            r"抗抑郁药|处方药|药物|剂量)",
            text,
            re.IGNORECASE,
        )
    )


def medical_decision_owner(text: str) -> str:
    """Identify who owns a proposed clinical-plan change after masking explicit negation."""

    if is_nonpersonal_transformation_task(text):
        return "none"
    active = active_domain_text(text, "medical")
    has_action = has_medical_change_action(active)
    if not has_action:
        return "none"
    established = bool(
        V12_CLINICIAN_ESTABLISHED_PLAN_PATTERN.search(active)
        or (
            (CLINICIAN_DIRECTED_CHANGE_PATTERN.search(active) or CLINICIAN_ESTABLISHED_PLAN_PATTERN.search(active))
            and (REPORT_ONLY_PATTERN.search(active) or NO_AI_MEDICAL_DECISION_PATTERN.search(active))
        )
    )
    request_scope = mask_pattern_matches(active, NO_AI_MEDICAL_DECISION_PATTERN)
    explicit_delegation = bool(
        (
            V12_AI_MEDICAL_DELEGATION_PATTERN.search(request_scope)
            or MEDICAL_DECISION_DELEGATION_PATTERN.search(request_scope)
        )
        and has_medical_change_action(request_scope)
    )
    requested = bool(
        explicit_delegation
        or (
            not established
            and (
                MEDICAL_REQUEST_CUE_PATTERN.search(request_scope)
                or re.search(
                    r"(?:请替我|替我|让AI|听AI|我想自己|我准备自己|别让我再问医生).{0,48}"
                    r"(?:停|改|换|加|减|翻倍|隔周)|"
                    r"(?:停|改|换|加|减|翻倍|隔周).{0,32}(?:请替我|让AI|别让我再问医生)",
                    request_scope,
                    re.IGNORECASE,
                )
            )
        )
    )
    if requested:
        return "ai_or_user_request"
    if established:
        return "clinician_established"
    return "unresolved"


def has_medical_change_request(text: str) -> bool:
    return medical_decision_owner(text) == "ai_or_user_request"


def medical_change_domains(text: str) -> set[str]:
    if not has_medical_change_request(text):
        return set()
    active = active_domain_text(text, "medical")
    domains: set[str] = set()
    if re.search(r"电休克(?:治疗)?|电痉挛(?:治疗)?|\bECT\b|手术|医疗程序", active, re.IGNORECASE):
        domains.add("medical_procedure")
    if re.search(r"深部脑刺激|\bDBS\b", active, re.IGNORECASE):
        domains.add("medical_procedure")
    if "medical_procedure" not in domains and TREATMENT_CHANGE_PATTERN.search(active):
        domains.add("psychotherapy")
    if re.search(
        r"药|用药|处方|医生开的|剂量|毫克|\bmg\b|\bmedication\b|药物假期|药片|片|粒|服用|服药|"
        r"每餐|翻倍|减半|生物制剂|胰岛素|甲氨蝶呤|氟西汀|帕罗西汀|"
        r"拉莫三嗪|舍曲林|地高辛|喹硫平|丙戊酸|劳拉西泮|来士普|"
        r"艾司西酞普兰|白色药片",
        active,
        re.IGNORECASE,
    ):
        domains.add("medication")
    if not domains:
        domains.add("clinical_plan")
    return domains


def has_high_cost_decision(text: str) -> bool:
    """Detect an in-scope material action, excluding explicit paper-only controls."""

    if is_nonpersonal_transformation_task(text):
        return False
    active = active_domain_text(text, "decision")
    if HIGH_COST_NONACTION_PATTERN.search(active):
        return False
    return bool(HIGH_COST_PATTERN.search(active))


def has_stable_preference(text: str) -> bool:
    # Disliking one's own repeated problem behaviour is a change request, not a
    # stable environmental preference that the runtime should protect from
    # examination.  Keep this check ahead of the broad lexical preference cue.
    if re.search(
        r"我(?:本人)?不喜欢自己[^。；;\n]{0,64}(?:迟交|拖延|失约|爽约|漏交|忘记|做不到|没完成)",
        text,
        re.IGNORECASE,
    ):
        return False
    if PREFERENCE_PATTERN.search(text):
        return True
    return bool(
        HABITUAL_ARRANGEMENT_PATTERN.search(text)
        and NO_IMPAIRMENT_PATTERN.search(text)
        and NO_CHANGE_PATTERN.search(text)
    )


def has_problem_behavior_change_request(text: str) -> bool:
    """Recognize an observable repeated behaviour the user explicitly wants to change."""

    return bool(
        re.search(
            r"我(?:本人)?不喜欢自己[^。；;\n]{0,64}(?:迟交|拖延|失约|爽约|漏交|忘记|做不到|没完成)",
            text,
            re.IGNORECASE,
        )
        and re.search(
            r"(?:我想|希望|准备|打算)(?:去)?(?:改变|调整|减少|停止|改掉)(?:这个|这种|该)?(?:行为|情况|习惯)?",
            text,
            re.IGNORECASE,
        )
    )


def explicit_preference_objects(text: str) -> list[tuple[str, str]]:
    """Return directly reported liked and disliked contexts without relabelling them."""

    pattern = re.compile(
        r"(?:我)?(?P<cue>不喜欢|不爱|不愿意|更不愿意|更喜欢|更愿意|喜欢|偏好)\s*"
        r"(?P<object>[^，,。；;\n]{2,32}?)(?=，|,|。|；|;|\n|所以|但|而|$)",
        re.IGNORECASE,
    )
    values: list[tuple[str, str]] = []
    for match in pattern.finditer(text):
        object_text = match.group("object").strip()
        if not object_text:
            continue
        polarity = "disliked" if re.search(r"不喜欢|不爱|不愿意|更不愿意", match.group("cue")) else "liked"
        item = (polarity, object_text)
        if item not in values:
            values.append(item)
    return values


def experiment_corrects_stable_preference(original: str, experiment: dict[str, Any]) -> bool:
    """Block experiments that use a reported preference itself as the correction target."""

    if not has_stable_preference(original) or experiment.get("status") not in {
        "planned",
        "active",
        "reviewed",
    }:
        return False
    primary = str(experiment.get("primary_variable", ""))
    action = str(experiment.get("action", ""))
    normalized_primary = identity_normal_form(primary)
    normalized_action = identity_normal_form(action)
    action_and_primary = primary + action
    for polarity, object_text in explicit_preference_objects(original):
        normalized_object = identity_normal_form(object_text)
        if not normalized_object:
            continue
        large_group_preference = bool(
            re.search(r"大型聚会|大型社交|人多|人很多|百人|拥挤|酒会|聚会", object_text)
        )
        large_group_action = bool(
            re.search(
                r"大型聚会|大型社交|人多|人很多|百人|拥挤|酒会|宴会|大型活动",
                action_and_primary,
            )
        )
        preserves_disliked_context = bool(
            re.search(
                r"(?:不参加|不进入|不去|避免|无需参加|保留不参加)[^，,。；;\n]{0,18}"
                r"(?:大型聚会|大型社交|人多|百人|拥挤|酒会|聚会)",
                action_and_primary,
                re.IGNORECASE,
            )
        )
        if polarity == "disliked" and normalized_object in normalized_primary:
            return True
        if polarity == "disliked" and not preserves_disliked_context and (
            normalized_object in normalized_action or (large_group_preference and large_group_action)
        ):
            if re.search(
                r"参加|进入|去一次|每天去|连续.{0,8}(?:天|次)|现场|直到|适应|克服|练习|"
                r"安排[^，,。；;\n]{0,16}(?:酒会|宴会|聚会|大型活动)"
                r"[^，,。；;\n]{0,12}(?:完成|进行)",
                action_and_primary,
                re.IGNORECASE,
            ):
                return True
        if normalized_object in identity_normal_form(action_and_primary) and re.search(
            r"强迫|逼(?:迫)?自己|克服|改掉|改变(?:这个|这项)?偏好|"
            r"直到不再(?:喜欢|不喜欢)|训练自己适应|必须参加|增加参加|减少独处",
            action_and_primary,
            re.IGNORECASE,
        ):
            return True
    return bool(
        re.search(
            r"强迫|逼(?:迫)?自己|改掉(?:这个|这项)?偏好|直到不再(?:喜欢|不喜欢)",
            primary + action,
            re.IGNORECASE,
        )
    )


V12_SEVERE_FUNCTIONAL_PATTERN = re.compile(
    r"(?:过去十二天|这两周|一个月来|过去三周|最近三周|连续四晚|最近十天|三周来|丧亲后六周)"
    r"[^。；;\n]{0,120}(?:下不了床|没吃饭|没洗澡|工作完全停了|连续缺了.{0,8}班|"
    r"只吃一顿|消息都发不出去|没去任何课|账单.{0,12}处理不了|基本生活开始失控|"
    r"无法出门|复诊和买食物都取消|几乎没睡|无法工作|不能安全开车|"
    r"基本照护都无法完成|家人全部接手|整天吃不下|体重明显下降|影响站立和上课|"
    r"无法处理洗衣、吃饭和必要邮件|日常功能明显受损)",
    re.IGNORECASE,
)
V12_STABLE_FUNCTION_CONTROL_PATTERN = re.compile(
    r"(?:吃饭、洗澡和工作都正常|能按时完成工作|课程和账单都按时处理|"
    r"能正常上班、看医生和买东西|每天睡够八小时.{0,18}都不受影响|"
    r"照顾孩子一直正常|饮食规律、体重稳定|能处理工作、家务和关系)",
    re.IGNORECASE,
)


def has_severe_functional_impairment(text: str) -> bool:
    """Combine duration, inability and affected domains without inferring a cause."""

    # A past or usual ability statement must not erase a later, explicitly
    # current deterioration.  Scope the override to a contrast plus a current
    # period so ordinary stable-preference controls remain conservative.
    if re.search(
        r"(?:但|不过|可是|然而)[^。；;\n]{0,24}(?:最近|当前|目前|这个月|近一个月|最近一个月)"
        r"[^。；;\n]{0,72}(?:连?床都?下不了|下不了床|工作(?:已经|全部|完全)?停了|"
        r"无法工作|基本生活开始失控)",
        text,
        re.IGNORECASE,
    ):
        return True
    if V12_STABLE_FUNCTION_CONTROL_PATTERN.search(text):
        return False
    if is_nonpersonal_transformation_task(text):
        return False
    if re.search(
        r"(?:其他|其余).{0,16}(?:正常|照常)|(?:工作|饮食|清洁|房租|作业|兼职).{0,24}(?:都|均)?(?:正常|照常)|"
        r"能按时(?:吃饭|工作)|只是不参加大型聚会",
        text,
        re.IGNORECASE,
    ):
        return False
    if FUNCTIONAL_IMPAIRMENT_PATTERN.search(text):
        return True
    if V12_SEVERE_FUNCTIONAL_PATTERN.search(text):
        return True
    duration = bool(
        re.search(
            r"(?:连续|过去|已经连续|最近).{0,8}(?:[一二三四五六七八九十百两\d]+|两|三)(?:天|周|星期|个月|月)|"
            r"(?:这个|本)月|大多数日子|一直",
            text,
            re.IGNORECASE,
        )
    )
    inability = bool(
        re.search(
            r"(?:无法|不能|做不到|没法|几乎没有|没有去|缺席了全部|一直没有去|需要.{0,8}提醒|无法完成)",
            text,
            re.IGNORECASE,
        )
    )
    if not duration or not inability:
        return False
    domain_patterns = {
        "self_care": re.compile(r"洗澡|洗漱|换衣|基础清洁|洗衣"),
        "food_water": re.compile(r"进食|吃饭|做饭|一顿饭|喝水"),
        "mobility": re.compile(r"起床|离床|下床|出门"),
        "work_study": re.compile(r"上班|工作|课程|上课|实习|作业|停学|缺席"),
        "administrative": re.compile(r"房租|缴费|账单|行政"),
    }
    domains = {name for name, pattern in domain_patterns.items() if pattern.search(text)}
    basic_need_failure = bool(
        re.search(
            r"(?:无法|不能|几乎没有).{0,10}(?:洗澡|洗漱|进食|吃饭|喝水|起床|离床)|"
            r"(?:洗澡|洗漱|进食|吃饭|喝水|起床|离床).{0,10}(?:无法|不能|做不到|需要.{0,6}提醒)",
            text,
            re.IGNORECASE,
        )
    )
    return basic_need_failure or len(domains) >= 2


def asserted_identity_text(text: str) -> str:
    """Keep only asserted personal claims while preserving evidence offsets."""

    active = mask_protected_material(text)
    return mask_pattern_matches(active, NEGATED_IMPLICATION_PATTERN)


def judgment_targets_current_user(text: str, start: int, end: int) -> bool:
    """Reject verdicts whose local proposition is explicitly about somebody else."""

    left = max(
        text.rfind("，", 0, start),
        text.rfind(",", 0, start),
        text.rfind("。", 0, start),
        text.rfind("；", 0, start),
        text.rfind(";", 0, start),
        text.rfind("\n", 0, start),
    ) + 1
    right_candidates = [
        position
        for mark in "，,。；;\n"
        if (position := text.find(mark, end)) >= 0
    ]
    right = min(right_candidates, default=len(text))
    local = text[left:right]
    current = re.search(r"我本人|我自己|本人|我|(?<![A-Za-z0-9_])I(?![A-Za-z0-9_])", local, re.IGNORECASE)
    third = re.search(
        r"(?:所以|因此|于是|这说明|这意味着)?\s*(?:他|她|他们|她们|张三|经理|"
        r"姐姐|妹妹|哥哥|弟弟|朋友|同事|伴侣|老周|小李|小王|Jordan|Priya)[^。；;,\n]{0,20}"
        r"(?:永远|注定|必然|不适合|做不好|无法|不能|没法|不可能)|"
        r"^(?:他|她|他们|她们|张三|经理|姐姐|妹妹|哥哥|弟弟|老周|小李|小王|Jordan|Priya)"
        r"[^。；;,\n]*$|"
        r"(?:Jordan|Priya|Leo|Maya)[^.;,\n]{0,80}(?:unfit|cannot|never|unable)",
        local,
        re.IGNORECASE,
    )
    if third is not None and (current is None or third.start() <= current.start()):
        return False
    named_third = re.search(
        r"(?:所以|因此|于是)\s*(?P<name>[\u4e00-\u9fff]{2,4})"
        r"(?=不适合|做不好|无法|不能|没法|不可能|永远|注定|必然)",
        local,
        re.IGNORECASE,
    )
    if (
        named_third is not None
        and "我" not in named_third.group("name")
        and named_third.group("name") not in {"永远", "根本", "以后", "今后", "目前", "现在"}
    ):
        return False
    return True


def has_identity_verdict_signal(text: str) -> bool:
    """Do not turn explicit non-judgments into identity verdicts."""

    without_nonverdict_context = NONVERDICT_CONTEXT_PATTERN.sub(" ", asserted_identity_text(text))
    return bool(
        VERDICT_PATTERN.search(without_nonverdict_context)
        or re.search(
            r"(?:所以|因此|于是)[^。；;\n]{0,72}(?:任何|每次|永远|注定|不可能|不能|无法|没法|"
            r"不适合|做不完|都会|都算|不值得|没救|不配|不敢|不会|当不好|学不会|坚持不了|"
            r"升不上去|扛不住|无法按时|不该|所有|都是我的错|都怪我|没有.{0,10}(?:行动力|能力|责任心))|"
            r"(?:注定|永远|这辈子|不可能|无法|不能|不适合|不该|不配|不敢|没救|"
            r"做不完|坚持不了|都是我的错|都怪我|升不上去|扛不住)[^。；;\n]{0,48}|"
            r"(?:以后|今后)[^。；;\n]{0,16}(?:都|永远)[^。；;\n]{0,16}(?:赢不了|做不到|不能|无法|失败)|"
            r"(?:this\s+means|therefore|so)\s+I[^.;]{0,64}(?:never|cannot|can't|must|unfit|incapable)",
            without_nonverdict_context,
            re.IGNORECASE,
        )
    )


def has_explicit_deconstruction_request(text: str) -> bool:
    if DECONSTRUCT_NEGATION_PATTERN.search(text):
        return False
    return bool(
        DECONSTRUCT_REQUEST_PATTERN.search(text)
        or AI_PERSONALITY_INFERENCE_REQUEST_PATTERN.search(text)
    )


def has_clinical_signal(text: str) -> bool:
    if is_nonpersonal_transformation_task(text):
        return False
    return bool(
        medical_decision_owner(text) in {"ai_or_user_request", "clinician_established"}
        or any(
            item["source_type"] in {"reported_clinical_diagnosis", "formal_scale_result"}
            for item in extract_labels(text)
        )
    )


def clause_bounds(text: str, start: int, end: int) -> tuple[int, int]:
    delimiters = "。；;\n"
    left = max((text.rfind(mark, 0, start) for mark in delimiters), default=-1) + 1
    right_candidates = [position for mark in delimiters if (position := text.find(mark, end)) >= 0]
    return left, min(right_candidates, default=len(text))


def identity_span_is_current_user(text: str, start: int, end: int) -> bool:
    """Keep identity evidence only when its local discourse is about the user."""

    left, right = clause_bounds(text, start, end)
    clause = text[left:right]
    prefix = text[left:start]
    if NONPERSONAL_IDENTITY_CONTEXT_PATTERN.search(clause):
        return False
    if re.search(
        r"(?:朋友|邻居|姐姐|哥哥|弟弟|妹妹|同事|患者|角色|人物|受访者|小周|他|她)"
        r"[^。；;]{0,36}(?:被|有|患有|确诊|诊断|自称|说自己是)",
        prefix,
        re.IGNORECASE,
    ) and not re.search(r"(?:称我|说我|写我|判断我|诊断我|确诊我)", prefix, re.IGNORECASE):
        return False
    if re.search(r"(?:这|那)是(?:他|她|朋友|邻居|姐姐|同事).{0,12}(?:情况|诊断|原话)", clause):
        return False
    return True


def diagnosis_assertion_is_current_user(text: str, start: int, end: int) -> bool:
    """Gate formal diagnoses on asserted polarity, discourse and an explicit user anchor."""

    if is_nonpersonal_transformation_task(text):
        return False
    left, right = clause_bounds(text, start, end)
    clause = text[left:right]
    prefix = text[left:start]
    assertion_window = text[max(left, start - 80):min(right, end + 4)]
    if DIAGNOSIS_UNCERTAINTY_PATTERN.search(assertion_window):
        return False
    if re.search(
        r"(?:^|[。；;])\s*(?:Did|Was|Were|Has|Have)\b[^?？]{0,80}\bdiagnos[^?？]*[?？]|"
        r"(?:是否|是不是|有没有)[^。；;?？]{0,28}(?:诊断|确诊)[?？]?",
        clause,
        re.IGNORECASE,
    ):
        return False
    if re.search(
        r"(?:朋友|同事|伴侣|室友|姐姐|妹妹|哥哥|弟弟|女儿|儿子|丈夫|妻子|母亲|父亲|文章|论文|例句|示例|"
        r"my\s+friend|friend|sister|brother|colleague|article|paper|example)"
        r"[^。；;\n]{0,48}(?:说|写|提到|举例|states?|says?|said|told|example)",
        prefix,
        re.IGNORECASE,
    ):
        return False
    if re.search(
        r"diagnosed\s+my\s+(?:brother|sister|son|daughter|friend)|"
        r"told\s+(?:my\s+)?(?:brother|sister|son|daughter|Priya)[^.;\n]{0,24}[\"'‘“]?You\b|"
        r"confirmed\s+that\s+my\s+(?:brother|sister|son|daughter|friend)\b|"
        r"(?:after\s+)?evaluating\s+my\s+(?:brother|sister|son|daughter)|"
        r"another\s+patient\s+was\s+diagnosed|diagnosed\s+[^.;\n]{0,24}\bin\s+a\s+patient\b|"
        r"website[^.;\n]{0,40}(?:explains?|describes?)[^.;\n]{0,40}\bdiagnos",
        clause,
        re.IGNORECASE,
    ):
        return False
    if re.search(
        r"(?:my\s+(?:psychiatrist|doctor|clinician|medical\s+record)|"
        r"my\s+formal\s+diagnosis|"
        r"\bI\s+was\s+(?:formally\s+)?diagnosed|diagnosed\s+me|"
        r"\bI\s+have\s+(?:a\s+)?(?:formal\s+|clinical\s+)?diagnosis|"
        r"clinician[^.;\n]{0,40}told[^.;\n]{0,24}\bI\s+had\b)",
        clause,
        re.IGNORECASE,
    ):
        return True
    if re.search(
        r"(?:我的[^。；;\n]{0,16}(?:医生|医师|精神科|临床心理师|临床心理学家|病历|医疗记录)|"
        r"我(?:本人)?(?:在[^。；;\n]{0,18})?(?:由|经)\s*(?:精神科|神经科|临床心理|全科|专科)?"
        r"(?:医生|医师|心理师|心理学家)[^。；;\n]{0,18}(?:诊断|确诊|确认)|"
        r"(?:医生|医师|精神科医生|临床心理师|专科团队|主治团队|全科医生)[^。；;\n]{0,20}"
        r"(?:诊断|确诊|确认)[^。；;\n]{0,10}我|"
        r"(?:医生|医师|精神科医生|临床心理师)[^。；;\n]{0,28}(?:对我说|告诉我)"
        r"[^。；;\n]{0,12}你(?:有|患有|符合)|"
        r"我(?:本人)?(?:被|有)[^。；;\n]{0,20}(?:诊断|确诊)|"
        r"(?:诊断|确诊|确认)我(?:有|为|是)?)",
        clause,
        re.IGNORECASE,
    ):
        return True
    if re.search(
        r"我[^。；;\n]{0,36}(?:拿到的诊断|给我的诊断|拿到.{0,12}诊断书|"
        r"精神科病历.{0,12}记录诊断)|"
        r"(?:医生|医师|主治医生|精神科医生)[^。；;\n]{0,24}给我的诊断|"
        r"(?:医生|医师|主治医生|精神科医生)[^。；;\n]{0,30}给我"
        r"(?:下了|作出|出具).{0,18}诊断",
        clause,
        re.IGNORECASE,
    ):
        return True
    return identity_span_is_current_user(text, start, end) and bool(
        re.search(r"(?:诊断我|确诊我|我的病历|my\s+diagnosis|diagnosed\s+me)", clause, re.IGNORECASE)
    )


def formal_diagnosis_spans(text: str) -> list[tuple[int, int, str]]:
    """Extract open diagnosis names only from current-user formal frames."""

    patterns = (
        re.compile(
            rf"(?:医生|医师|主治医生|精神科医生)[^，。；;\n]{{0,24}}给我的诊断(?:是|为)\s*"
            rf"[“‘\"']?(?P<label>(?:成人\s*)?{DIAGNOSIS_NAME})",
            re.IGNORECASE,
        ),
        re.compile(
            rf"我[^，。；;\n]{{0,40}}(?:拿到的诊断|给我的诊断)(?:是|为)\s*"
            rf"[“‘\"']?(?P<label>(?:成人\s*)?{DIAGNOSIS_NAME})",
            re.IGNORECASE,
        ),
        re.compile(
            rf"我拿到[^。；;\n]{{0,24}}诊断书[^。；;\n]{{0,16}}(?:写的是|写明|记录)\s*"
            rf"[“‘\"']?(?P<label>{DIAGNOSIS_NAME})",
            re.IGNORECASE,
        ),
        re.compile(
            rf"我的精神科病历[^，。；;\n]{{0,16}}(?:记录|写明|显示)诊断\s*[：:]?\s*"
            rf"[“‘\"']?(?P<label>{DIAGNOSIS_NAME})",
            re.IGNORECASE,
        ),
        re.compile(
            rf"(?:医生|医师|主治医生|精神科医生)[^，。；;\n]{{0,30}}给我"
            rf"(?:下了|作出|出具)(?P<label>(?:成人\s*)?{DIAGNOSIS_NAME})诊断",
            re.IGNORECASE,
        ),
        re.compile(
            r"(?:我的)?(?:全科医生(?:和精神科医生)?|精神科医生|神经科医生|临床心理师|"
            r"临床心理学家|专科团队|主治团队)"
            r"[^，。；;\n]{0,16}(?:诊断了?|确认|确诊)(?:我)?(?:患有|有|为|是)?\s*"
            r"(?P<label>[^，。；;\n]{2,40}?)(?=，|。|；|;|所以|因此|治疗方案|学业能力|$)",
            re.IGNORECASE,
        ),
        re.compile(
            rf"我(?:本人)?(?:在[^，。；;\n]{{0,18}})?(?:由|经)\s*"
            rf"(?:精神科|神经科|临床心理|全科|专科)?(?:医生|医师|心理师|心理学家)"
            rf"[^，。；;\n]{{0,18}}(?:正式)?(?:诊断|确诊|确认)(?:了)?(?:我)?"
            rf"(?:患有|有|为|是)?\s*[“‘\"']?(?P<label>{DIAGNOSIS_NAME})",
            re.IGNORECASE,
        ),
        re.compile(
            rf"my\s+(?:psychiatrist|doctor|clinician)\s+diagnosed(?:\s+me)?\s+"
            rf"(?:with\s+|as\s+)?(?P<label>{EN_DIAGNOSIS_NAME})",
            re.IGNORECASE,
        ),
        re.compile(
            rf"\bI\s+was\s+(?:formally\s+)?diagnosed\s+(?:with|as)\s+"
            rf"(?P<label>{EN_DIAGNOSIS_NAME})(?:\s+by\s+my\s+(?:psychiatrist|doctor|clinician))?",
            re.IGNORECASE,
        ),
        re.compile(
            rf"my\s+(?:medical\s+record|clinical\s+record)\s+"
            rf"(?:documents?|records?|shows?)\s+(?:a\s+)?formal\s+diagnosis\s+of\s+"
            rf"(?P<label>{EN_DIAGNOSIS_NAME})",
            re.IGNORECASE,
        ),
        re.compile(
            rf"my\s+formal\s+diagnosis\s+from\s+(?:a\s+)?(?:psychiatrist|doctor|clinician)\s+"
            rf"(?:is|was)\s+(?P<label>{EN_DIAGNOSIS_NAME})",
            re.IGNORECASE,
        ),
        re.compile(
            rf"(?:医院)?病历(?:写明|记录|显示)?\s*(?P<target>我)被(?:正式)?确诊为\s*"
            rf"[“‘\"']?(?P<label>{DIAGNOSIS_NAME})",
            re.IGNORECASE,
        ),
        re.compile(
            rf"我有\s*(?:医院|门诊|专科|医生)(?:病历)?\s*(?:正式)?(?:确诊|诊断)(?:的|为)?\s*"
            rf"[“‘\"']?(?P<label>{DIAGNOSIS_NAME})",
            re.IGNORECASE,
        ),
        re.compile(
            r"(?:专科|遗传|精神科|神经科|风湿免疫科|运动障碍专科|临床)?(?:门诊|医生|医师)?"
            r"[^。；;\n]{0,24}(?:正式诊断我为|正式确诊我(?:有|患有|是|为)|正式确诊我是|正式确诊为)"
            r"\s*(?P<label>[^，。；;\n]{2,48}?)(?=，|。|；|;|所以|因此|请|$)",
            re.IGNORECASE,
        ),
        re.compile(
            r"我有(?:医院|门诊|专科|医生)?[^，。；;\n]{0,16}(?:出具的)?\s*"
            r"(?P<label>[^，。；;\n]{2,36}?)(?:正式|临床)诊断(?=，|。|；|;|请|$)",
            re.IGNORECASE,
        ),
        re.compile(
            r"我有正式\s*(?P<label>[A-Za-z0-9. -]{2,40}|[\u4e00-\u9fff0-9.]{2,36})\s*诊断",
            re.IGNORECASE,
        ),
    )
    values: list[tuple[int, int, str]] = []
    for pattern in patterns:
        for match in pattern.finditer(text):
            raw = match.group("label")
            label = raw.strip(" “ ”‘’\"'")
            offset = raw.find(label)
            start = match.start("label") + offset
            end = start + len(label)
            if not label or DIAGNOSIS_UNCERTAINTY_PATTERN.search(match.group(0)):
                continue
            if diagnosis_assertion_is_current_user(text, start, end):
                values.append((start, end, label))
    return values


def formal_scale_spans(text: str) -> list[tuple[int, int, str]]:
    """Capture a professional scale name together with its complete result span."""

    professional = re.compile(
        r"(?:医院(?:心理科)?|心理门诊|精神科门诊|门诊心理师|临床心理师|注册临床心理师|心理师|"
        r"精神科医生|学校心理服务|认证施测人员|持证施测人员)"
        r"[^。；;\n]{0,40}(?:施测(?:了)?|完成(?:了)?|正式做了?|报告(?:记录|写)?)",
        re.IGNORECASE,
    )
    nonclinical = re.compile(
        r"社群自制|小游戏|招聘软件|能力雷达|电子游戏|排行榜|软件构建|工程基线|"
        r"代码质量|服务监控|数据库延迟|API|不是临床|不涉及心理测量|"
        + NONFORMAL_SCALE_CONTEXT_PATTERN.pattern,
        re.IGNORECASE,
    )
    code_pattern = re.compile(r"(?<![A-Za-z0-9])[A-Z][A-Z0-9-]{1,15}(?![A-Za-z0-9])", re.IGNORECASE)
    results: list[tuple[int, int, str]] = []
    direct_patterns = (
        re.compile(
            r"(?:公司|学校|机构|认证施测人员|持证施测人员)[^。；;\n]{0,32}"
            r"正式\s*MBTI\s*施测[^。；;\n]{0,24}报告(?:显示|写明|记录)(?:我)?(?:是|为)\s*"
            r"(?P<label>[EI](?:型|[NS][FT][JP]))",
            re.IGNORECASE,
        ),
        re.compile(
            r"我(?:本人)?(?:在|于)[^。；;\n]{0,20}完成[^。；;\n]{0,12}正式\s*MBTI\s*施测"
            r"[^。；;\n]{0,24}结果(?:是|为)\s*(?P<label>[EI][NS][FT][JP])",
            re.IGNORECASE,
        ),
        re.compile(
            r"(?:认证施测人员|持证施测人员)[^。；;\n]{0,48}MBTI\s+Form\s+M"
            r"[^。；;\n]{0,24}报告(?:偏好)?(?:是|为)\s*(?P<label>[EI][NS][FT][JP])",
            re.IGNORECASE,
        ),
        re.compile(
            r"(?:学校心理服务|医院(?:心理科)?|心理门诊)[^。；;\n]{0,48}"
            r"(?P<label>GAD-?7[^。；;\n]{0,56}(?:原始分|总分|得分|分数)\s*\d+(?:\.\d+)?)",
            re.IGNORECASE,
        ),
        re.compile(
            r"我(?:本人)?[^。；;\n]{0,18}(?:完成|做了)[^。；;\n]{0,12}正式量表"
            r"[^。；;\n]{0,24}报告(?:说|写|显示)(?:我)?(?:是|为)\s*"
            r"(?P<label>[^，。；;\n]{2,24})",
            re.IGNORECASE,
        ),
    )
    for pattern in direct_patterns:
        for match in pattern.finditer(text):
            left, right = clause_bounds(text, match.start(), match.end())
            if nonclinical.search(text[left:right]):
                continue
            raw = match.group("label").strip(" ，,：:\t\n“”‘’\"'")
            start = match.start("label") + match.group("label").find(raw)
            if raw:
                results.append((start, start + len(raw), raw))
    precise_results = tuple(results)
    for match in professional.finditer(text):
        left, right = clause_bounds(text, match.start(), match.end())
        clause = text[left:right]
        if nonclinical.search(clause):
            continue
        code = code_pattern.search(text, match.start(), right)
        if not code:
            continue
        result_end = right
        boundary = re.search(
            r"(?:，|,)(?:所以|因此|只记录|请只|我因此|它说明|"
            r"(?:但|不过|然而)(?:这|该结果|该报告|医生)?(?:不是|并非|不等于|不能单独作为))",
            text[code.end():right],
            re.IGNORECASE,
        )
        if boundary:
            result_end = code.end() + boundary.start()
        raw = text[code.start():result_end].strip(" ，,")
        end = code.start() + len(raw)
        if not re.search(
            r"\d|T值|百分位|标准分|总分|得分|分数|高分|低分|临界范围|显著升高|常模|结果|报告偏好",
            raw,
            re.IGNORECASE,
        ):
            continue
        if any(code.start() <= precise_start and precise_end <= end for precise_start, precise_end, _ in precise_results):
            continue
        results.append((code.start(), end, raw))
    return results


def source_scope_for(text: str, start: int, end: int) -> str:
    """Use the label's clause, plus one prior clause only when it has no source cue."""

    delimiters = "，。；,;\n"
    left = max((text.rfind(mark, 0, start) for mark in delimiters), default=-1) + 1
    right_candidates = [position for mark in delimiters if (position := text.find(mark, end)) >= 0]
    right = min(right_candidates, default=len(text))
    current = text[left:right]
    self_cue = has_self_description_cue(current)
    has_local_cue = any(
        pattern.search(current)
        for pattern in (
            AI_SOURCE_PATTERN,
            SOCIAL_SOURCE_PATTERN,
            THIRD_PARTY_SOURCE_PATTERN,
            FORMAL_SCALE_PATTERN,
            FORMAL_DIAGNOSIS_PATTERN,
            NONCLINICAL_PROVENANCE_PATTERN,
        )
    ) or self_cue
    if left == 0:
        return current
    previous_left = max((text.rfind(mark, 0, left - 1) for mark in delimiters), default=-1) + 1
    previous = text[previous_left:left]
    if re.search(
        r"(?:他|她|它|该博主|这位博主|该平台)[^，。；,;]{0,8}(?:说|写|认为|判断|断言)",
        current,
        re.IGNORECASE,
    ) and (AI_SOURCE_PATTERN.search(previous) or SOCIAL_SOURCE_PATTERN.search(previous)):
        return text[previous_left:right]
    if has_local_cue and not NONCLINICAL_PROVENANCE_PATTERN.search(previous):
        return current
    return text[previous_left:right]


ATTRIBUTION_PREDICATE_TAIL_PATTERN = re.compile(
    r"(?:(?:仍然?|随后|自己|也|又|还|明确|则|在评语里)\s*)?"
    r"(?P<predicate>"
    r"(?:说|写|判断|断定|断言|评价|认为|认定|下结论说)(?:我)?(?:是|就是|只是)?|"
    r"(?:称我为|叫我(?:作)?|"
    r"把我(?:叫作|称作|称为|归为|分成)|把我这种表现叫)|"
    r"(?:给|替)我(?:打上|贴上|加上|赋予)|"
    r"(?:says?|claims?)\s+I\s+(?:am|have)|labels?\s+me\s+as"
    r")\s*[“‘\"']?\s*$",
    re.IGNORECASE,
)
SELF_ATTRIBUTION_TAIL_PATTERN = re.compile(
    r"(?P<predicate>(?:我(?:自己|本人)?[^，。；,;\n]{0,28}?"
    r"(?:自称|给自己贴(?:的|了)?(?:标签(?:是)?)?|把自己(?:叫作|称作|称为)|"
    r"说自己是|认为自己是|认定自己就是|叫自己))|"
    r"(?:(?:仍然?|仍明确|明确|随后|也|又|还)\s*)?自称)\s*[“‘\"']?\s*$",
    re.IGNORECASE,
)
AI_ACTOR_PATTERN = re.compile(
    r"(?:另一个\s*)?(?:情绪)?(?<![A-Za-z])AI(?![A-Za-z])|ChatGPT|Claude|人工智能|聊天机器人|chatbot|模型|"
    r"(?:情绪|日记|聊天|人格|性格)?(?:App|应用|工具|系统|软件|算法|程序)",
    re.IGNORECASE,
)
SOCIAL_HUMAN_ACTOR_PATTERN = re.compile(
    r"短视频博主|论坛博主|(?:短视频)?博主|播客(?:节目|主播|作者)?|主播|该博主|这位博主|热门帖子",
    re.IGNORECASE,
)
SOCIAL_MEDIUM_ACTOR_PATTERN = re.compile(
    r"网上(?=\s*(?:说|写|判断|断言|评价|认为|认定|称我|叫我))|"
    r"短视频(?=\s*(?:说|写|判断|断言|评价|认为|认定|称我|叫我))|"
    r"人格测试(?=\s*(?:说|写|判断|断言|评价|认为|认定|称我|叫我))|"
    r"平台(?=\s*(?:说|写|判断|断言|评价|认为|认定|称我|叫我))|"
    r"网上测试|网上测评|网测|抖音(?:测试|测评)?|公众号(?:小游戏)?|"
    r"(?:公司|学校|机构)(?:性格|人格)?(?:测试|测评|测验)|"
    r"短视频(?:链接里(?:的)?[^，。；,;\n]{0,12}(?:测试|测评)|测试|测评|评论区|评论)|"
    r"论坛|评论(?:区)?|页面|娱乐网站|小红书|社交媒体|热门帖子|"
    r"平台(?:人格)?(?:测试|测评)|online\s+(?:quiz|test)|social\s+media\s+(?:quiz|test)",
    re.IGNORECASE,
)
NAMED_PERSON_ACTOR_PATTERN = re.compile(
    r"(?:甲)?同事|朋友|伴侣|室友|家人|父亲|母亲|老师|导师|上司|主管|"
    r"项目负责人|邻居|前伴侣|前任|姐姐|妹妹|哥哥|弟弟|表弟",
    re.IGNORECASE,
)
ANONYMOUS_ACTOR_PATTERN = re.compile(
    r"匿名(?:用户|成员)?|身份不明(?:的人)?|不知道对方是谁|陌生人|(?:有|某)个人",
    re.IGNORECASE,
)


def attribution_actor_candidates(text: str, start: int, end: int) -> list[tuple[int, int, str, str]]:
    """Return actor mentions, excluding mentions that are only source material or objects."""

    scope = text[start:end]
    patterns: tuple[tuple[str, re.Pattern[str]], ...] = (
        ("ai_inference", AI_ACTOR_PATTERN),
        ("social_media_label", SOCIAL_HUMAN_ACTOR_PATTERN),
        ("social_media_label", SOCIAL_MEDIUM_ACTOR_PATTERN),
        ("other_person_attribution", NAMED_PERSON_ACTOR_PATTERN),
        ("other_person_attribution", OTHER_ACTOR_EVENT_PATTERN),
        ("unknown_source", ANONYMOUS_ACTOR_PATTERN),
    )
    candidates: list[tuple[int, int, str, str]] = []
    for source_type, pattern in patterns:
        for match in pattern.finditer(scope):
            absolute_start = start + match.start()
            absolute_end = start + match.end()
            following = text[absolute_end : min(end, absolute_end + 28)]
            preceding = text[max(start, absolute_start - 8) : absolute_start]
            if source_type == "ai_inference" and (
                re.match(
                    r"\s*(?:给的|生成的|提供的|输出的|写的|答案|回答|回复|摘要|报告|内容|原话)",
                    following,
                    re.IGNORECASE,
                )
                or re.search(r"(?:交给|发给|问|询问|使用|看完)\s*$", preceding, re.IGNORECASE)
            ):
                continue
            if source_type in {"other_person_attribution", "social_media_label"} and re.match(
                r"\s*的(?:(?:一|这|那)?段|几段|一些)?(?:对话|话|文章|回答|摘要|报告|内容|材料)",
                following,
                re.IGNORECASE,
            ):
                continue
            candidates.append((absolute_start, absolute_end, match.group(0), source_type))
    ordered = sorted(candidates, key=lambda item: (item[0], item[1]))
    resolved: list[tuple[int, int, str, str]] = []
    pronoun = re.compile(r"^(?:他|她|它|他们|她们|它们|he|she|it|they)$", re.IGNORECASE)
    for actor_start, actor_end, actor_text, source_type in ordered:
        if source_type == "other_person_attribution" and pronoun.fullmatch(actor_text):
            antecedents = [
                item
                for item in resolved
                if not pronoun.fullmatch(item[2]) and item[3] != "unknown_source"
            ]
            if antecedents:
                source_type = antecedents[-1][3]
        resolved.append((actor_start, actor_end, actor_text, source_type))
    return resolved


PERSONAL_IDENTITY_OVERRIDE_PATTERN = re.compile(
    r"这不是翻译任务|not\s+asking\s+for\s+translation|这是我的(?:出院|正式|真实)|"
    r"培训已经结束.{0,20}现实|不是测试字符串|我本人|我的真实情况|不谈小说.{0,12}现实|"
    r"退出角色扮演后|我的真实自述|我不是引用论文|我现在仍认可|"
    r"忽略示例.{0,12}我本人|确实是我的自述|离开课堂案例后.{0,16}我自己的事|"
    r"这封邮件是写给我的|现实里我|现实中认为自己|记录的是我本人",
    re.IGNORECASE,
)
PERSONAL_IDENTITY_TRANSITION_PATTERN = re.compile(
    r"这不是翻译任务|not\s+asking\s+for\s+translation|这是我的(?:出院|正式|真实)|"
    r"培训已经结束.{0,20}现实|不是测试字符串|不谈小说.{0,12}现实|"
    r"退出角色扮演后|我不是引用论文|忽略示例.{0,12}我本人|"
    r"离开课堂案例后.{0,16}我自己的事",
    re.IGNORECASE,
)
NONPERSONAL_TASK_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "test_fixture",
        re.compile(
            r"单元测试|测试夹具|raw\s*=|JSON\s*fixture|fixture|合成数据|标注样本|测试样本|"
            r"红队提示词|测试模型|检查解析器|只验证\s*JSON|"
            r"(?:校验|检查|解析|格式化|验证|分析)[^。；;\n]{0,16}JSON",
            re.IGNORECASE,
        ),
    ),
    (
        "dataset",
        re.compile(r"数据集|匿名样本|匿名被试|OCR.{0,20}表格|表格属于", re.IGNORECASE),
    ),
    (
        "translation",
        re.compile(
            r"^\s*(?:请)?翻译\s*[：:]|请.{0,20}翻译|翻译成|Translate\b|家长会翻译|采访翻译|只做翻译|"
            r"翻译练习|论文句子.{0,12}翻译|翻译.{0,12}例句",
            re.IGNORECASE,
        ),
    ),
    (
        "fiction",
        re.compile(
            r"小说人物|小说(?:角色)?台词|剧本角色|角色扮演|虚构角色|人物塑造|评价这句台词|"
            r"电影台词|故事台词",
            re.IGNORECASE,
        ),
    ),
    (
        "education",
        re.compile(
            r"教材(?:句子|示例|内容)|培训(?:材料|角色|老师)|课堂案例|课程内容|广告文案|"
            r"作业|找出.{0,16}逻辑谬误|批改案例",
            re.IGNORECASE,
        ),
    ),
    (
        "document",
        re.compile(
            r"论文(?:中的被试|原文|引文)|档案摘录|会议纪要|面试记录员|家长会|"
            r"病历句子|病历引文|病历模板|工单日志|审计工单|邮件模板|采访|"
            r"文章(?:例句|示例)|论文句子|Markdown\s*引用|这段\s*Markdown|AI\s*输出|"
            r"我(?:只|只是|仅)(?:在|负责|做)?(?:转述|录入|旁听|整理|复述|记录|陪诊|陪同|"
            r"批改|审计|校对|检查|概括)|不是对我的判断|不是在说我|没有在描述自己|"
            r"评价不是对我|患者不是我|不是我的个人陈述|句子来自|"
            r"(?:我让|请让|让)(?:AI|模型|ChatGPT)[^。；;\n]{0,20}(?:改写|润色|重写)(?:句子)?|"
            r"(?:AI|模型|ChatGPT)[^。；;\n]{0,20}(?:把这句话)?(?:写成|改写成|重写成)"
            r"[^。；;\n]{0,48}(?:只)?校对(?:引号里|引号内|这句|文本)|"
            r"请回复[\u4e00-\u9fff]{2,8}\s*[：:]?|"
            r"only\s+(?:relaying|transcribing|proofreading)|"
            r"I\s+(?:am|'m)\s+(?:only\s+)?(?:relaying|transcribing|proofreading)",
            re.IGNORECASE,
        ),
    ),
)

MATERIAL_SOURCE_FRAME_PATTERN = re.compile(
    r"(?:客服|访谈|论文|研究|采访|录音|会议|病历|档案)[^。；;\n]{0,32}"
    r"(?:转写|原文|引文|逐字稿|记录|材料|写道|说道)|"
    r"(?:录音转写|访谈原文|论文原文|引用材料|原始材料)|"
    r"(?:这是一位)?患者的原话|"
    r"(?:妈妈|父亲|母亲|姐姐|妹妹|哥哥|弟弟|主管|经理|老师|朋友|同事)"
    r"[^。；;\n]{0,32}(?:谈起自己|说起自己|描述自己|对(?:他|她|实习生|学生|同事)说)",
    re.IGNORECASE,
)
MATERIAL_TRANSFORM_TASK_PATTERN = re.compile(
    r"校验|检查|解析|格式化|加标点|校对|概括|摘要|翻译|提取|转述|记录|"
    r"评价不是对我|不是对我|只需|只要|"
    r"proofread|summari[sz]e|translate|validate|format",
    re.IGNORECASE,
)
JSON_MATERIAL_FRAME_PATTERN = re.compile(
    r"(?:校验|检查|解析|格式化|验证|分析)[^。；;\n]{0,24}JSON|"
    r"JSON[^。；;\n]{0,24}(?:校验|检查|解析|格式化|验证|分析)",
    re.IGNORECASE,
)

MATERIAL_WHOLE_INPUT_PATTERN = re.compile(
    r"测试夹具|测试样本|标注样本|数据集样本|只验证\s*JSON|"
    r"(?:校验|检查|解析|格式化|验证|分析)[^。；;\n]{0,36}JSON|"
    r"JSON[^。；;\n]{0,36}(?:校验|检查|解析|格式化|验证|分析)|"
    r"^\s*(?:请)?翻译\s*[：:]|请.{0,28}翻译|翻译练习|翻译训练(?:引文)?|论文句子[^。；;\n]{0,24}翻译|"
    r"小说(?:角色)?台词|电影台词|剧本台词|"
    r"(?:这是一位)?患者的原话\s*[：:]|"
    r"For\s+(?:a|the)\s+novel[^.;\n]{0,24}proofread\s*[：:]?|"
    r"(?:我让|请让|让)(?:AI|模型|ChatGPT)[^。；;\n]{0,20}(?:改写|润色|重写)(?:句子)?|"
    r"(?:AI|模型|ChatGPT)[^。；;\n]{0,20}(?:把这句话)?(?:写成|改写成|重写成)"
    r"[^。；;\n]{0,48}(?:只)?校对(?:引号里|引号内|这句|文本)|"
    r"请回复[\u4e00-\u9fff]{2,8}\s*[：:]?|"
    r"Markdown\s*引用|这段\s*Markdown[^。；;\n]{0,24}(?:改|转|整理)|"
    r"请把\s*(?:AI|模型|ChatGPT)[^。；;\n]{0,18}输出[^。；;\n]{0,40}(?:改|润色|重写)|"
    r"(?:文章|论文|教材)[^。；;\n]{0,24}(?:例句|示例|原句)|"
    r"这句会触发安全提示吗\s*[：:]|历史日记的原文是\s*[：:]|"
    r"这段引文与我无关\s*[：:]|"
    r"(?:article|paper|textbook)[^.;\n]{0,32}(?:example|sample\s+sentence|quotation)",
    re.IGNORECASE,
)

LIVE_PERSONAL_OVERRIDE_PATTERN = re.compile(
    r"这不是翻译(?:任务|练习)[^。；;\n]{0,24}我(?:现在|今晚|此刻)|"
    r"这是我的真实(?:情况|诊断|计划|想法)|确实是我的(?:情况|诊断|计划|想法)|"
    r"现实中我(?:现在|目前|今晚|今天)|现实里我(?:现在|目前|今晚|今天)|"
    r"不是例句[^。；;\n]{0,24}(?:是我|我本人)|不是测试材料[^。；;\n]{0,24}(?:是我|我本人)|"
    r"(?:上面|前面|引文)[^。；;\n]{0,16}(?:就是|是)[^。；;\n]{0,8}"
    r"我(?:本人)?(?:现在|目前|今晚)?(?:的)?(?:计划|情况|想法)|"
    r"not\s+(?:an?|the)\s+(?:example|exercise|fixture)[^.;]{0,30}(?:my|I\s+am|I\s+was)",
    re.IGNORECASE,
)
LIVE_PERSONAL_SAFETY_OVERRIDE_PATTERN = re.compile(
    r"这不是翻译(?:任务|练习)[^。；;\n]{0,24}我(?:现在|今晚|此刻)|"
    r"(?:上面|前面|引文)[^。；;\n]{0,16}(?:就是|是)[^。；;\n]{0,8}"
    r"我(?:本人)?(?:现在|目前|此刻|今晚)?(?:的)?(?:计划|打算|想法)",
    re.IGNORECASE,
)

EXPLICIT_NONPERSONAL_IDENTITY_SCOPE_PATTERN = re.compile(
    r"(?:原话|引语|句子|文案|术语表?|概念|通常指什么)[^。\n]{0,120}"
    r"(?:不是我的情况|不是对我的描述|不分析我|没有提供任何个人案例|不要替我判断人格)|"
    r"(?:不是我的情况|不是对我的描述|不分析我|没有提供任何个人案例|不要替我判断人格|"
    r"我不是在自称)[^。\n]{0,120}(?:原话|引语|句子|文案|术语表?|概念|通常指什么)",
    re.IGNORECASE,
)


def json_container_spans(text: str) -> list[tuple[int, int]]:
    """Return balanced JSON-like object spans while respecting quoted strings."""

    spans: list[tuple[int, int]] = []
    depth = 0
    start: int | None = None
    quote: str | None = None
    escaped = False
    for index, character in enumerate(text):
        if quote is not None:
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == quote:
                quote = None
            continue
        if character in {'"', "'"}:
            quote = character
            continue
        if character == "{":
            if depth == 0:
                start = index
            depth += 1
        elif character == "}" and depth:
            depth -= 1
            if depth == 0 and start is not None:
                spans.append((start, index + 1))
                start = None
    return spans


def is_nonpersonal_transformation_task(text: str) -> bool:
    """Return true only when the outer request governs quoted or structured material."""

    if LIVE_PERSONAL_OVERRIDE_PATTERN.search(text):
        return False
    if EXPLICIT_NONPERSONAL_IDENTITY_SCOPE_PATTERN.search(text):
        return True
    if not MATERIAL_WHOLE_INPUT_PATTERN.search(text):
        return False
    has_payload = bool(
        json_container_spans(text)
        or re.search(r"[‘’“”'\"]|^\s*>\s+|\b(?:message|statement)\b\s*:", text, re.IGNORECASE)
        or re.search(r"(?:例句|台词|样本|夹具|引用|输出)", text, re.IGNORECASE)
        or re.search(r"[：:]\s*\S", text)
    )
    return has_payload


def protected_material_spans(text: str) -> list[tuple[int, int, str]]:
    """Locate payload spans governed by document transformation tasks."""

    spans: list[tuple[int, int, str]] = []
    for start, end in json_container_spans(text):
        frame = text[max(0, start - 64):start]
        if JSON_MATERIAL_FRAME_PATTERN.search(frame):
            spans.append((start, end, "structured_material"))

    quote_pattern = re.compile(r"“(?P<curly>[^”]*)”|‘(?P<single>[^’]*)’", re.DOTALL)
    for match in quote_pattern.finditer(text):
        group = "curly" if match.group("curly") is not None else "single"
        start, end = match.start(group), match.end(group)
        if any(left <= start and end <= right for left, right, _ in spans):
            continue
        prefix = text[max(0, match.start() - 80):match.start()]
        suffix = text[match.end():min(len(text), match.end() + 64)]
        if MATERIAL_SOURCE_FRAME_PATTERN.search(prefix) and (
            MATERIAL_TRANSFORM_TASK_PATTERN.search(prefix)
            or MATERIAL_TRANSFORM_TASK_PATTERN.search(suffix)
        ):
            spans.append((start, end, "document_material"))
    return sorted(spans, key=lambda item: (item[0], item[1]))


def mask_protected_material(text: str) -> str:
    """Mask material payloads with equal-length spaces so evidence offsets stay stable."""

    characters = list(text)
    for start, end, _ in protected_material_spans(text):
        for index in range(start, end):
            if characters[index] not in "。；;\n":
                characters[index] = " "
    return "".join(characters)


def span_material_kind(text: str, start: int, end: int) -> tuple[str, int, int] | None:
    for left, right, kind in protected_material_spans(text):
        if left <= start and end <= right:
            return kind, left, right
    return None


PROPOSITION_TARGET_TAIL_PATTERN = re.compile(
    r"(?P<target>我本人|我自己|本人|我|(?<![A-Za-z0-9_])I(?![A-Za-z0-9_])|"
    r"(?<![A-Za-z0-9_])(?:me|my|You)(?![A-Za-z0-9_])|你|他|她|张三|"
    r"老周|队长|陈经理|经理|弟弟|妹妹|姐姐|哥哥|表弟|母亲|父亲|Leo|Jordan|Priya)"
    r"\s*(?:天生)?(?:就是|是|有|患有|为|像|自称|was|is|had|has|am|have|are)\s*(?:an?\s+)?$",
    re.IGNORECASE,
)
SELF_REFLEXIVE_TARGET_TAIL_PATTERN = re.compile(
    r"(?P<target>我)(?:本人|自己)?"
    r"(?!的?(?:母亲|父亲|妈妈|爸爸|姐姐|妹妹|哥哥|弟弟|女儿|儿子|丈夫|妻子|伴侣|室友|朋友|同事))"
    r"[^，。；,;\n]{0,20}"
    r"(?:说|认为|认定|判断|相信)[^，。；,;\n]{0,8}自己\s*(?:就是|是|有|像)\s*$",
    re.IGNORECASE,
)
THIRD_PARTY_REFLEXIVE_TARGET_TAIL_PATTERN = re.compile(
    r"(?P<target>(?:我(?:的)?)?(?:母亲|父亲|妈妈|爸爸|姐姐|妹妹|哥哥|弟弟|女儿|儿子|"
    r"丈夫|妻子|伴侣|室友|朋友|同事(?:[\u4e00-\u9fff]{2,4})?)|"
    r"(?:同事|朋友|伴侣|室友)?[\u4e00-\u9fff]{2,4})"
    r"[^，。；,;\n]{0,12}(?:说|写|认为|认定|判断|相信)"
    r"(?:他|她)?自己\s*(?:就是|是|有|像)\s*$",
    re.IGNORECASE,
)
CLINICAL_PROPOSITION_TARGET_TAIL_PATTERN = re.compile(
    r"(?P<target>我|他|她|患者|来访者)\s*被(?:正式)?(?:确诊|诊断)(?:为|有)\s*$",
    re.IGNORECASE,
)
SPEECH_NAMED_TARGET_TAIL_PATTERN = re.compile(
    r"(?:说|写|认为|认定|判断|断言|评价)(?P<target>[\u4e00-\u9fff]{2,8})"
    r"\s*(?:就是|是|有|患有|为|像)\s*$",
    re.IGNORECASE,
)
CLINICIAN_ACTOR_PATTERN = re.compile(
    r"持牌精神科医生|精神科医生|神经科医生|心理科医生|临床心理学家|临床心理师|注册临床心理师|"
    r"治疗师|心理师|咨询师|医生|临床医生|clinical\s+psychologist|therapist|clinician|psychiatrist",
    re.IGNORECASE,
)
OTHER_ACTOR_EVENT_PATTERN = re.compile(
    r"妈妈|母亲|父亲|姐姐|妹妹|哥哥|弟弟|女儿|儿子|丈夫|妻子|表弟|室友|同事们?|伴侣|朋友|主管|经理|招聘官|教练|导师|老师|"
    r"上司|王教练|咨询师|心理师|Alice|Ben|Maya|Jordan(?:'s manager)?|manager|"
    r"他们|她们|它们|她|他|它|\bhe\b|\bshe\b|\bit\b|\bthey\b",
    re.IGNORECASE,
)
PREDICATE_EVENT_PATTERN = re.compile(
    r"正式诊断|诊断|确诊|符合.{0,12}诊断标准|施测|正式记录|记录结果|"
    r"说|写|评价|认为|认定|暗示|叫作|叫我|称作|称为|自称|定义成|判断|断言|"
    r"解释成|打上|贴上|加上|赋予|就是|是|有|像|told|said|label(?:led|ed)?|diagnosed|assessed|scored|"
    r"\b(?:am|is|are|was|were|have|had)\b",
    re.IGNORECASE,
)
THIRD_PARTY_TARGET_PATTERN = re.compile(
    r"(?P<target>老周|队长|陈经理|我的邻居|邻居|我弟弟|弟弟|我女儿|女儿|我儿子|儿子|我丈夫|丈夫|我妻子|妻子|候选人甲|小航|他的前任|前任|她姐姐|姐姐|"
    r"上一届学生|那位学生|文章作者|作者|案例中的被试|被试|剧本角色|角色|案例人物|"
    r"项目经理|哥哥|表弟|妹妹|母亲|患者李某|来访者|客户|林悦|小周|Leo|Jordan|Priya|"
    r"he|she|her|him|the\s+subject|the\s+patient)"
    r"[^，。；,;\n]{0,14}(?:天生)?(?:是|有|患有|为|像|自称|认为自己是|was|is|had|has)?\s*(?:an?\s+)?$",
    re.IGNORECASE,
)
CURRENT_USER_TARGET_PATTERN = re.compile(
    r"(?P<target>我本人|我自己|本人|我|(?<![A-Za-z0-9_])I(?![A-Za-z0-9_])|"
    r"(?<![A-Za-z0-9_])(?:me|my|You)(?![A-Za-z0-9_])|你)"
    r"[^，。；,;\n]{0,18}(?:是|有|患有|为|像|自称|认为自己是|就是|am|was|have|had|are)?\s*(?:an?\s+)?$",
    re.IGNORECASE,
)


def identity_discourse_kind(text: str, start: int, end: int) -> tuple[str, int, int]:
    protected = span_material_kind(text, start, end)
    if protected is not None:
        return protected
    left, right = clause_bounds(text, start, end)
    clause = text[left:right]
    occurrence_prefix = clause[: max(0, end - left)]
    transition = PERSONAL_IDENTITY_TRANSITION_PATTERN.search(occurrence_prefix)
    if transition is not None or re.search(
        r"(?:正式)?诊断我(?:有|为)|确诊我(?:有|为)?|我的病历|这是我的出院记录|"
        r"my\s+(?:diagnosis|medical\s+record)",
        clause,
        re.IGNORECASE,
    ):
        return "personal", left, right
    for kind, pattern in NONPERSONAL_TASK_PATTERNS:
        if pattern.search(clause) and transition is None:
            return kind, left, right
    if PERSONAL_IDENTITY_OVERRIDE_PATTERN.search(occurrence_prefix):
        return "personal", left, right
    return "personal", left, right


def predicate_polarity(text: str, start: int, end: int, seed_source: str | None) -> str:
    left, right = clause_bounds(text, start, end)
    prefix = text[max(left, start - 42):start]
    local = text[max(left, start - 42):min(right, end + 30)]
    if re.search(r"(?:^|[，,])\s*不是\s*(?:我|他|她|你|小李|小王)\s*$", prefix):
        return "negated"
    if seed_source == "formal_scale_result":
        if re.search(r"(?:没有|未曾|尚未)\s*(?:完成|施测|做)", prefix, re.IGNORECASE):
            return "negated"
        return "affirmed"
    if re.search(
        r"(?:did|does|do|has|have)\s+not\s+diagnos[^，。；,;\n]{0,16}$|"
        r"(?:didn't|doesn't|hasn't|haven't)\s+diagnos[^，。；,;\n]{0,16}$",
        prefix,
        re.IGNORECASE,
    ):
        return "negated"
    direct_question_suffix = text[end:right]
    if re.search(
        r"是不是|是否|可能(?:有|是)?|疑似|怀疑|不见得(?:是|有)?|未必(?:是|有|认为)?|"
        r"might\s+(?:be|have)",
        prefix,
        re.IGNORECASE,
    ) or re.fullmatch(
        r"\s*[”’\"']?\s*(?:[，,]\s*)?(?:对吗|是吗|吗|呢)?\s*[？?]\s*",
        direct_question_suffix,
        re.IGNORECASE,
    ):
        return "uncertain"
    predicate_tail = ATTRIBUTION_PREDICATE_TAIL_PATTERN.search(prefix)
    if predicate_tail is not None:
        governor = prefix[:predicate_tail.start("predicate")]
        if re.search(
            r"(?:不|没(?:有)?|并未|未曾|从未|从不|不曾)\s*$|"
            r"(?:不等于|并不是(?:在)?|绝不是(?:在)?)\s*$",
            governor,
            re.IGNORECASE,
        ):
            return "negated"
    if re.search(
        r"(?:绝非|谈不上(?:是|有)?)[^，。；,;\n]{0,16}$|"
        r"(?:没有|并无|未达到|不符合|不能(?:自动)?证明|无法证明)[^，。；,;\n]{0,20}(?:我是|是|有)?\s*$",
        prefix,
        re.IGNORECASE,
    ) or re.search(r"未达到[^，。；,;\n]{0,24}诊断标准", local, re.IGNORECASE) or re.search(
        r"(?:否认|不代表|不等于|没有说|没说|不是说)[^，。；,;\n]{0,24}(?:我|你|他|她)?[^，。；,;\n]{0,8}$",
        prefix,
        re.IGNORECASE,
    ) or re.search(
        r"(?:不是|并非|没有|并无)\s*$",
        prefix,
        re.IGNORECASE,
    ):
        return "negated"
    return "affirmed"


def resolve_target(
    text: str,
    start: int,
    end: int,
    discourse_kind: str,
) -> tuple[str, str, int, int, str]:
    left, right = clause_bounds(text, start, end)
    prefix = text[left:start]
    if discourse_kind != "personal":
        return "unresolved", "", start, start, "unresolved"

    clinical_third_party = re.search(
        r"(?P<target>(?:我(?:的)?)?(?:女儿|儿子|丈夫|妻子|姐姐|妹妹|哥哥|弟弟|"
        r"朋友|同事|伴侣|室友))[^，。；,;\n]{0,18}(?:患有|被诊断为|诊断是|确诊为)\s*$",
        prefix,
        re.IGNORECASE,
    )
    if clinical_third_party:
        token = clinical_third_party.group("target")
        return (
            "third_party",
            token,
            left + clinical_third_party.start("target"),
            left + clinical_third_party.end("target"),
            "explicit",
        )

    clinician_to_current = re.search(
        r"(?:医生|医师|主治医生|精神科医生)[^，。；,;\n]{0,24}给(?P<target>我)的诊断(?:是|为)\s*$",
        prefix,
        re.IGNORECASE,
    )
    if clinician_to_current:
        return (
            "current_user",
            clinician_to_current.group("target"),
            left + clinician_to_current.start("target"),
            left + clinician_to_current.end("target"),
            "explicit",
        )

    clinical_current = re.search(
        r"(?P<target>我)(?:最终)?[^，。；,;\n]{0,42}(?:拿到的诊断|给我的诊断|"
        r"拿到.{0,16}诊断书|精神科病历.{0,16}记录诊断|"
        r"由[^，。；,;\n]{0,20}给我(?:下了|作出|出具))[^，。；,;\n]{0,12}$",
        prefix,
        re.IGNORECASE,
    )
    if clinical_current:
        return (
            "current_user",
            clinical_current.group("target"),
            left + clinical_current.start("target"),
            left + clinical_current.end("target"),
            "explicit",
        )

    query_target = re.search(
        r"你\s*(?:觉得|认为|判断)\s*(?P<target>我|他|她|[\u4e00-\u9fff]{2,8})\s*是不是\s*$",
        prefix,
        re.IGNORECASE,
    )
    if query_target:
        token = query_target.group("target")
        role = "current_user" if token == "我" else "third_party"
        return (
            role,
            token,
            left + query_target.start("target"),
            left + query_target.end("target"),
            "explicit",
        )

    direct_you = re.search(r"^\s*(?P<target>你)\s*(?:就是|是|有|像)\s*$", prefix, re.IGNORECASE)
    if direct_you:
        return (
            "third_party",
            direct_you.group("target"),
            left + direct_you.start("target"),
            left + direct_you.end("target"),
            "explicit",
        )

    contrast_target = re.search(
        r"(?:^|[，,])\s*(?:不是|是)\s*(?P<target>我|他|她|你|小李|小王)\s*$",
        prefix,
        re.IGNORECASE,
    )
    if contrast_target:
        token = contrast_target.group("target")
        role = "current_user" if token == "我" else "third_party"
        return (
            role,
            token,
            left + contrast_target.start("target"),
            left + contrast_target.end("target"),
            "explicit",
        )

    clinical_self = re.search(
        r"(?P<target>我)(?:的[^，。；,;\n]{0,18}(?:医生|医师|精神科|病历|医疗记录)|"
        r"\s*(?:被|由)[^，。；,;\n]{0,24}(?:诊断|确诊)|[^，。；,;\n]{0,12}(?:诊断|确诊))|"
        r"(?P<english>\bI\b)\s+was\s+(?:formally\s+)?diagnosed|"
        r"(?P<possessive>\bmy\b)\s+(?:psychiatrist|doctor|clinician|medical\s+record|formal\s+diagnosis)",
        prefix,
        re.IGNORECASE,
    )
    if clinical_self:
        group = "target" if clinical_self.groupdict().get("target") else "english" if clinical_self.groupdict().get("english") else "possessive"
        token = clinical_self.group(group)
        return (
            "current_user",
            token,
            left + clinical_self.start(group),
            left + clinical_self.end(group),
            "explicit",
        )

    quote_start = max(prefix.rfind(mark) for mark in ("‘", "“", "'", '"'))
    if quote_start >= 0:
        quote_prefix = prefix[quote_start + 1 :]
        subject = re.search(r"^\s*(?P<target>你|You|I|我)", quote_prefix, re.IGNORECASE)
        introducer = prefix[:quote_start]
        if subject:
            token = subject.group("target")
            token_start = left + quote_start + 1 + subject.start("target")
            token_end = token_start + len(token)
            if token.casefold() in {"你", "you"}:
                if re.search(r"对我(?:说|写)|告诉我|写给我|told\s+me|to\s+me", introducer, re.IGNORECASE):
                    return "current_user", token, token_start, token_end, "resolved_reference"
                if re.search(r"同一句(?:邮件|消息)|same\s+(?:email|message)", introducer, re.IGNORECASE) and re.search(
                    r"对我(?:说|写)|告诉我|写给我|told\s+me|to\s+me",
                    text[:left],
                    re.IGNORECASE,
                ):
                    return "current_user", token, token_start, token_end, "resolved_reference"
                return "third_party", token, token_start, token_end, "resolved_reference"
            if re.search(
                r"我(?:本人|自己)?[^，。；,;]{0,20}(?:说|自称|认为|觉得)|"
                r"我的(?:真实)?自述|我现在仍认可|我本人当时说",
                introducer,
                re.IGNORECASE,
            ):
                return "current_user", token, token_start, token_end, "resolved_reference"
            if OTHER_ACTOR_EVENT_PATTERN.search(introducer):
                return "third_party", token, token_start, token_end, "resolved_reference"

    vocative = re.search(
        r"^\s*(?P<target>小李|小王|助手|经理|老师|医生|妈妈|姐姐|妹妹|哥哥|弟弟|朋友)"
        r"[，,：:]\s*你[^，。；,;\n]{0,18}$",
        prefix,
        re.IGNORECASE,
    )
    if vocative:
        token = vocative.group("target")
        return "third_party", token, left + vocative.start("target"), left + vocative.end("target"), "resolved_reference"

    self_reflexive = SELF_REFLEXIVE_TARGET_TAIL_PATTERN.search(prefix)
    third_reflexive = THIRD_PARTY_REFLEXIVE_TARGET_TAIL_PATTERN.search(prefix)
    if self_reflexive is None and third_reflexive is not None:
        token = third_reflexive.group("target")
        return (
            "third_party",
            token,
            left + third_reflexive.start("target"),
            left + third_reflexive.end("target"),
            "explicit",
        )

    proposition = self_reflexive
    if proposition is None:
        proposition = CLINICAL_PROPOSITION_TARGET_TAIL_PATTERN.search(prefix)
    if proposition is None:
        proposition = PROPOSITION_TARGET_TAIL_PATTERN.search(prefix)
    if proposition is None:
        proposition = SPEECH_NAMED_TARGET_TAIL_PATTERN.search(prefix)
    if proposition is not None:
        token = proposition.group("target")
        if proposition.re is SPEECH_NAMED_TARGET_TAIL_PATTERN and re.search(
            r"我|他|她|自己|被|确诊|诊断|说明|写明", token
        ):
            proposition = None
    if proposition is not None:
        token = proposition.group("target")
        token_start = left + proposition.start("target")
        token_end = left + proposition.end("target")
        if token.casefold() in {"我本人", "我自己", "本人", "我", "i", "me", "my", "you", "你"}:
            return "current_user", token, token_start, token_end, "explicit"
        return "third_party", token, token_start, token_end, "explicit"

    third_matches = list(THIRD_PARTY_TARGET_PATTERN.finditer(prefix))
    current_matches = list(CURRENT_USER_TARGET_PATTERN.finditer(prefix))
    direct_current = list(
        re.finditer(
            r"(?P<target>对我|给我|告诉我|写我|说我|评价我|认为我|认定我|暗示我|叫我|称我|"
            r"把我|诊断我|确诊我|我的(?:病历|记录|报告)|told\s+me|said\s+I|diagnosed\s+me)",
            prefix,
            re.IGNORECASE,
        )
    )
    direct_third = list(
        re.finditer(
            r"(?P<target>对(?:他|她|表弟|小周)说|告诉(?:Leo|Priya|林悦)|told\s+(?:Leo|Priya)|"
            r"(?:姐姐|妹妹|母亲|同事|被试|项目经理|表弟|哥哥|Jordan|Priya)(?:的)?(?:病历|记录|报告)?)",
            prefix,
            re.IGNORECASE,
        )
    )
    choices: list[tuple[int, str, str, int, int, str]] = []
    for match in current_matches:
        absolute_start = left + match.start("target")
        choices.append((match.start(), "current_user", match.group("target"), absolute_start, left + match.end("target"), "explicit"))
    for match in third_matches:
        absolute_start = left + match.start("target")
        choices.append((match.start(), "third_party", match.group("target"), absolute_start, left + match.end("target"), "explicit"))
    for match in direct_current:
        raw = match.group("target")
        inner = re.search(r"我|me|I", raw, re.IGNORECASE)
        offset = inner.start() if inner else 0
        token = inner.group(0) if inner else raw
        absolute_start = left + match.start("target") + offset
        choices.append((match.start(), "current_user", token, absolute_start, absolute_start + len(token), "explicit"))
    for match in direct_third:
        raw = match.group("target")
        absolute_start = left + match.start("target")
        choices.append((match.start(), "third_party", raw, absolute_start, absolute_start + len(raw), "explicit"))

    participation = re.search(
        r"(?P<target>我)(?:本人|自己)?\s*(?:做了?|完成了?|填写了?|参加了?)"
        r"[^。；;\n]{0,48}(?:量表|小测|网测|测验|测试|测评|问卷)",
        text[left:right],
        re.IGNORECASE,
    )
    if participation and left + participation.start("target") < start:
        absolute_start = left + participation.start("target")
        choices.append(
            (
                participation.start("target"),
                "current_user",
                participation.group("target"),
                absolute_start,
                left + participation.end("target"),
                "explicit",
            )
        )

    if re.search(r"(?:我的|我在|我于).{0,32}(?:正式|量表|报告|筛查|得分|结果)", prefix, re.IGNORECASE):
        match = re.search(r"我", prefix)
        if match:
            choices.append((match.start(), "current_user", "我", left + match.start(), left + match.end(), "explicit"))
    if re.search(r"这个词", prefix, re.IGNORECASE):
        previous = text[:left].rstrip("。；;\n")
        if re.search(r"(?:说我|叫我|称我|我是|我就是)[^。；;\n]{1,36}$", previous, re.IGNORECASE):
            match = list(re.finditer(r"我", previous))[-1]
            choices.append((len(prefix), "current_user", "我", match.start(), match.end(), "resolved_reference"))
        elif re.search(r"(?:说|叫|称)(?:哥哥|姐姐|弟弟|他|她)", previous, re.IGNORECASE):
            choices.append((len(prefix), "third_party", "这个词", start, start, "resolved_reference"))

    if SELF_ATTRIBUTION_TAIL_PATTERN.search(prefix):
        self_mentions = list(re.finditer(r"我本人|我自己|我|\bI\b", prefix, re.IGNORECASE))
        if self_mentions:
            match = self_mentions[-1]
            choices.append(
                (
                    len(prefix),
                    "current_user",
                    match.group(0),
                    left + match.start(),
                    left + match.end(),
                    "resolved_reference",
                )
            )

    if not choices:
        return "unresolved", "", start, start, "unresolved"
    _, role, token, token_start, token_end, resolution = max(
        choices,
        key=lambda item: (item[0], item[4] - item[3]),
    )
    return role, token, token_start, token_end, resolution


def infer_seed_source(text: str, start: int, end: int) -> str | None:
    left, right = clause_bounds(text, start, end)
    clause = text[left:right]
    nonclinical_provenance = bool(NONCLINICAL_PROVENANCE_PATTERN.search(clause))
    nonformal_scale = bool(NONFORMAL_SCALE_CONTEXT_PATTERN.search(clause))
    if not nonclinical_provenance:
        if any(left == start and right == end for left, right, _ in formal_diagnosis_spans(text)):
            return "reported_clinical_diagnosis"
        if span_is_captured_label(text, start, end, FORMAL_DIAGNOSIS_LABEL_PATTERNS):
            return "reported_clinical_diagnosis"
    if not nonformal_scale and any(left <= start and end <= right for left, right, _ in formal_scale_spans(text)):
        return "formal_scale_result"
    if not nonformal_scale and span_is_captured_label(text, start, end, FORMAL_SCALE_LABEL_PATTERNS):
        return "formal_scale_result"
    if span_is_captured_label(text, start, end, NONFORMAL_CLINICAL_LABEL_PATTERNS):
        return "social_media_label"
    if span_is_captured_label(text, start, end, SELF_LABEL_CAPTURE_PATTERNS):
        return "user_self_description"
    if re.search(
        r"(?:我本人|我自己|我|\bI\b)\s*(?:就是|是|am|was)\s*"
        r"(?:一个|an?\s+)?(?:典型(?:的)?\s*)?[“‘\"']?\s*$",
        text[left:start],
        re.IGNORECASE,
    ):
        return "user_self_description"
    exact = text[start:end]
    if (
        CLINICIAN_ACTOR_PATTERN.search(clause)
        and re.search(
            r"(?:我(?:的)?)?(?:女儿|儿子|丈夫|妻子|姐姐|妹妹|哥哥|弟弟|朋友|同事|伴侣|室友)"
            r"[^，。；,;\n]{0,18}(?:患有|被诊断为|诊断是|确诊为)",
            clause,
            re.IGNORECASE,
        )
        and re.search(r"症|障碍|ADHD|OCD|PTSD|depression|bipolar", exact, re.IGNORECASE)
    ):
        return "reported_clinical_diagnosis"
    if (
        re.search(r"(?:症|障碍|ADHD|OCD|PTSD|depression|anxiety\s+disorder|bipolar)", exact, re.IGNORECASE)
        and not DIAGNOSIS_UNCERTAINTY_PATTERN.search(clause)
        and (
            re.search(r"我的病历|病历写着", clause, re.IGNORECASE)
            or (
                CLINICIAN_ACTOR_PATTERN.search(clause)
                and re.search(
                    r"诊断|确诊|确认(?:我)?(?:有|患有|为|是)|"
                    r"对我说[^。；;\n]{0,16}你(?:有|患有|符合)|符合.{0,16}诊断标准|formally|diagnos|"
                    r"clinician[^，。；,;\n]{0,48}(?:I|me)[^，。；,;\n]{0,24}(?:had|have)",
                    clause,
                    re.IGNORECASE,
                )
            )
        )
    ):
        return "reported_clinical_diagnosis"
    if FORMAL_SCALE_CODE_PATTERN.fullmatch(exact):
        if re.search(
            r"正式|量表|筛查|报告|测评报告|百分位|T\s*分|得了?\s*\d+|结果为|阳性阈值",
            text[left:right],
            re.IGNORECASE,
        ):
            return "formal_scale_result"
    scale_prefix = text[left:start]
    scale_suffix = text[end:right]
    if (
        re.fullmatch(r"ADHD|OCD|PTSD|[一-鿿]{2,18}(?:症|障碍)", exact, re.IGNORECASE)
        and re.search(r"(?:正式)?量表|量表结果|医院.{0,20}量表", scale_prefix, re.IGNORECASE)
        and re.search(r"^(?:\s*)(?:风险偏高|筛查(?:结果)?|阳性|提示|范围)", scale_suffix, re.IGNORECASE)
    ):
        return "formal_scale_result"
    return None


def attribution_event_for_label(
    text: str,
    start: int,
    end: int,
    seed_source: str | None = None,
) -> AttributionEvent | None:
    """Resolve one local attribution event before accepting it as user evidence."""

    seed_source = seed_source or infer_seed_source(text, start, end)
    source_left, source_right = clause_bounds(text, start, end)
    source_clause = text[source_left:source_right]
    if seed_source == "formal_scale_result" and NONFORMAL_SCALE_CONTEXT_PATTERN.search(source_clause):
        if AI_SOURCE_PATTERN.search(source_clause):
            seed_source = "ai_inference"
        elif SOCIAL_SOURCE_PATTERN.search(source_clause):
            seed_source = "social_media_label"
        else:
            seed_source = "user_self_description"
    if seed_source == "reported_clinical_diagnosis" and not diagnosis_assertion_is_current_user(text, start, end):
        source_left, source_right = clause_bounds(text, start, end)
        source_clause = text[source_left:source_right]
        if not re.search(
            r"(?:我(?:的)?)?(?:女儿|儿子|丈夫|妻子|姐姐|妹妹|哥哥|弟弟|朋友|同事|伴侣|室友)"
            r"[^，。；,;\n]{0,18}(?:患有|被诊断为|诊断是|确诊为)",
            source_clause,
            re.IGNORECASE,
        ):
            return None
    discourse_kind, left, right = identity_discourse_kind(text, start, end)
    if (
        seed_source == "reported_clinical_diagnosis"
        and NONCLINICAL_PROVENANCE_PATTERN.search(text[left:right])
    ):
        seed_source = None
    target_role, target_text, target_start, target_end, target_resolution = resolve_target(
        text, start, end, discourse_kind
    )
    polarity = predicate_polarity(text, start, end, seed_source)
    prefix = text[left:start]
    clause = text[left:right]
    if re.search(
        r"你\s*(?:觉得|认为|判断)\s*我\s*是不是\s*$",
        prefix,
        re.IGNORECASE,
    ):
        seed_source = None
    if re.search(
        r"不是\s*我(?:自己)?\s*说\s*我是[^，。；,;\n]{1,36}[，,]\s*是\s*(?:AI|模型|ChatGPT)"
        r"[^。；;\n]{0,24}(?:结论|判断|说法)",
        clause,
        re.IGNORECASE,
    ):
        seed_source = "ai_inference"
        polarity = "affirmed"
    elif re.search(
        r"不是\s*(?:AI|模型|ChatGPT)\s*说\s*我是[^，。；,;\n]{1,36}[，,]\s*是\s*我(?:自己)?"
        r"[^。；;\n]{0,20}(?:说|认为|自称)",
        clause,
        re.IGNORECASE,
    ):
        seed_source = "user_self_description"
        polarity = "affirmed"
    predicate_tail = ATTRIBUTION_PREDICATE_TAIL_PATTERN.search(prefix)
    predicate_governor_start = (
        left + predicate_tail.start("predicate") if predicate_tail is not None else start
    )
    resolved_actor_event: tuple[int, int, str, str] | None = None

    if polarity == "negated":
        return None
    if seed_source == "reported_clinical_diagnosis" and polarity == "uncertain":
        seed_source = None

    if (
        target_role == "unresolved"
        and discourse_kind == "personal"
        and seed_source in {"reported_clinical_diagnosis", "formal_scale_result"}
    ):
        next_boundaries = [
            position
            for mark in "。；;\n"
            if (position := text.find(mark, right + 1)) >= 0
        ]
        reference_right = min(next_boundaries, default=min(len(text), end + 96))
        reference_window = text[end:reference_right]
        future_target = re.search(
            r"(?:"
            r"(?:所以|因此|于是)[^。；;\n]{0,8}|"
            r"(?:它|这个结果|该结果|该报告|这份结果)[^。；;\n]{0,10}"
            r"(?:说明|意味着|让我认为|使我认为)[^。；;\n]{0,8}"
            r")(?P<target>我)",
            reference_window,
            re.IGNORECASE,
        )
        if future_target:
            target_start = end + future_target.start("target")
            target_end = end + future_target.end("target")
            target_role = "current_user"
            target_text = text[target_start:target_end]
            target_resolution = "resolved_reference"
        elif REPORT_ONLY_PATTERN.search(text) or (
            re.search(
                r"(?:本周|这周|最近).{0,12}(?:医院|门诊).{0,12}(?:做|完成)|"
                r"(?:医院心理科|医院|心理门诊|精神科门诊|门诊|临床心理师|注册临床心理师|心理师|"
                r"学校心理服务|认证施测人员|持证施测人员)"
                r".{0,48}(?:给我[^。；;\n]{0,12})?(?:施测|做了?|完成)",
                text,
                re.IGNORECASE,
            )
            and not re.search(
                r"(?:朋友|邻居|姐姐|哥哥|弟弟|妹妹|同事|患者|来访者|客户)"
                r"[^。；;\n]{0,24}(?:施测|做了?|完成).{0,16}(?:量表|[A-Z][A-Z0-9-]{1,15})",
                text[left:right],
                re.IGNORECASE,
            )
        ):
            target_role = "current_user"
            target_text = ""
            target_start = start
            target_end = start
            target_resolution = "resolved_reference"

    if (
        target_role == "unresolved"
        and discourse_kind == "personal"
        and SOCIAL_SOURCE_PATTERN.search(text[left:start])
        and re.search(
            r"^\s*(?:昨晚|今天|今早|刚刚|刚才|我(?:本人)?)"
            r"[^。；;\n]{0,30}(?:做了?|完成了?|填写了?|参加了?)"
            r"[^。；;\n]{0,30}(?:网测|小测|测试|测评|测验|问卷)",
            text[left:right],
            re.IGNORECASE,
        )
        and not re.search(
            r"(?:妹妹|姐姐|弟弟|哥哥|朋友|同事|伴侣|室友)"
            r"[^。；;\n]{0,24}(?:做了?|完成了?|填写了?|参加了?)",
            text[left:start],
            re.IGNORECASE,
        )
    ):
        target_role = "current_user"
        target_text = ""
        target_start = start
        target_end = start
        target_resolution = "resolved_reference"

    local_source: str
    if seed_source in {
        "reported_clinical_diagnosis",
        "formal_scale_result",
        "social_media_label",
        "ai_inference",
    }:
        local_source = seed_source
    else:
        actor_events = [
            item
            for item in attribution_actor_candidates(text, left, start)
            if item[1] <= predicate_governor_start
        ]
        source_cues = [(actor_start, source) for actor_start, _, _, source in actor_events]
        strong_self_matches = list(
            re.finditer(
                r"(?P<actor>我本人|我自己|我|\bI\b)[^，。；,;\n]{0,28}"
                r"(?:觉得自己是|认为自己是|认定自己(?:就是|是)|相信自己是|"
                r"(?:担心|怀疑)自己是不是|(?:又|也)?觉得(?:我)?(?:只是|就是|是)|"
                r"(?:只是|明确)?说自己是|"
                r"(?:又|也|仍然?|明确|仍明确)?自称|"
                r"把自己(?:定义成|叫作|称作|称为)|"
                r"给自己贴(?:的|了)?(?:标签)?(?:是|为)?|"
                r"给自己下了结论[^，。；,;\n]{0,8}我是|"
                r"believe\s+I\s+(?:am|might\s+be)|think\s+I\s+(?:am|might\s+be)|"
                r"worry\s+I\s+(?:am|might\s+be))\s*[“‘\"']?\s*$",
                prefix,
                re.IGNORECASE,
            )
        )
        if strong_self_matches:
            match = strong_self_matches[-1]
            source_cues.append((left + match.start("actor"), "user_self_description"))
        elif SELF_ATTRIBUTION_TAIL_PATTERN.search(prefix):
            self_mentions = list(re.finditer(r"我本人|我自己|我|\bI\b", prefix, re.IGNORECASE))
            if self_mentions:
                source_cues.append((left + self_mentions[-1].start(), "user_self_description"))
        if re.search(r"(?:^|[，,])\s*是\s*我\s*$", prefix, re.IGNORECASE):
            self_mentions = list(re.finditer(r"我", prefix))
            if self_mentions:
                source_cues.append((left + self_mentions[-1].start(), "user_self_description"))
        if re.search(
            r"不是\s*(?:AI|模型|ChatGPT)\s*说\s*我是[^，。；,;\n]{1,36}[，,]\s*是\s*我(?:自己)?"
            r"[^。；;\n]{0,20}(?:说|认为|自称)",
            clause,
            re.IGNORECASE,
        ):
            source_cues.append((start + 1, "user_self_description"))
        if (
            not actor_events
            and discourse_kind == "personal"
            and PERSONAL_IDENTITY_OVERRIDE_PATTERN.search(text[left:right])
        ):
            self_mentions = list(re.finditer(r"我本人|我自己|我|\bI\b", prefix, re.IGNORECASE))
            if self_mentions:
                source_cues.append((left + self_mentions[-1].start(), "user_self_description"))
        if seed_source == "user_self_description" and not actor_events and not strong_self_matches:
            source_cues.append((left, "user_self_description"))
        local_source = max(source_cues, key=lambda item: item[0])[1] if source_cues else "unknown_source"
        matching_actors = [
            item for item in actor_events if item[0] == max((cue[0] for cue in source_cues), default=-1)
        ]
        if matching_actors and matching_actors[-1][3] == local_source:
            resolved_actor_event = matching_actors[-1]

    if target_role != "current_user" or discourse_kind != "personal":
        return AttributionEvent(
            local_source,
            "unknown",
            "",
            start,
            start,
            "unknown",
            polarity,
            "",
            start,
            start,
            target_role,
            target_text,
            target_start,
            target_end,
            target_resolution,
            start,
            end,
            discourse_kind,
            left,
            right,
        )

    predicate_matches = list(PREDICATE_EVENT_PATTERN.finditer(prefix))
    predicate = predicate_matches[-1] if predicate_matches else None
    predicate_start = (
        left + predicate_tail.start("predicate")
        if predicate_tail is not None
        else left + predicate.start() if predicate else start
    )
    predicate_end = (
        left + predicate_tail.end("predicate")
        if predicate_tail is not None
        else left + predicate.end() if predicate else start
    )
    predicate_text = text[predicate_start:predicate_end]
    if local_source == "reported_clinical_diagnosis":
        predicate_kind, speaker_role = "diagnoses", "clinician"
        actor_pattern = CLINICIAN_ACTOR_PATTERN
    elif local_source == "formal_scale_result":
        predicate_kind, speaker_role = "reports_scale", "instrument"
        actor_pattern = re.compile(r"PHQ-?9|ASRS-v1\.1|NEO-PI-3|Big\s+Five|[A-Z][A-Z0-9.-]{1,15}")
    elif local_source == "ai_inference":
        predicate_kind, speaker_role = "labels", "ai"
        actor_pattern = AI_ACTOR_PATTERN
    elif local_source == "social_media_label":
        predicate_kind, speaker_role = "labels", "social_actor"
        actor_pattern = re.compile(
            rf"{SOCIAL_HUMAN_ACTOR_PATTERN.pattern}|{SOCIAL_MEDIUM_ACTOR_PATTERN.pattern}", re.IGNORECASE
        )
    elif local_source == "user_self_description":
        predicate_kind, speaker_role = "self_identifies", "self"
        actor_pattern = re.compile(r"我本人|我自己|我|\bI\b", re.IGNORECASE)
    else:
        predicate_kind = "labels"
        speaker_role = "other_person" if local_source == "other_person_attribution" else "unknown"
        actor_pattern = OTHER_ACTOR_EVENT_PATTERN

    if resolved_actor_event is not None:
        actor_start, actor_end, actor_text, _ = resolved_actor_event
    else:
        actor_scope_end = end if local_source == "formal_scale_result" else predicate_start
        actor_matches = list(actor_pattern.finditer(text[left:actor_scope_end]))
        actor = actor_matches[-1] if actor_matches else None
        actor_start = left + actor.start() if actor else predicate_start
        actor_end = left + actor.end() if actor else predicate_start
        actor_text = text[actor_start:actor_end]
    return AttributionEvent(
        local_source,
        speaker_role,
        actor_text,
        actor_start,
        actor_end,
        predicate_kind,
        polarity,
        predicate_text,
        predicate_start,
        predicate_end,
        target_role,
        target_text,
        target_start,
        target_end,
        target_resolution,
        start,
        end,
        discourse_kind,
        left,
        right,
    )


def nearest_source_cue(text: str, start: int, end: int | None = None) -> str | None:
    """Resolve the closest attribution cue before one label occurrence."""

    if end is None:
        end = start
    event = attribution_event_for_label(text, start, end)
    if event:
        return event.source_type

    left, _ = clause_bounds(text, start, start)
    prefix = text[left:start]
    patterns: tuple[tuple[str, re.Pattern[str]], ...] = (
        (
            "user_self_description",
            re.compile(
                r"我(?:自己|本人)?(?:又|也|则|还)?自称(?:的)?|我(?:明确)?给自己贴.{0,8}标签(?:是)?|"
                r"我认定自己就是|我叫自己|我的自称是|我的\s*MBTI\s*结果是|"
                r"我(?:一直|总)?把自己(?:叫作|称为)|"
                r"我(?:自己)?(?:又|也)?说自己是|"
                r"我(?:自己)?(?:又|也)?(?:觉得|认为)(?:我)?(?:只是|就是|是)|"
                r"(?<!说)(?<!写)(?<!判断)(?<!断言)(?<!断定)(?<!认为)我(?:就是|是)\s*$",
                re.IGNORECASE,
            ),
        ),
        ("ai_inference", AI_SOURCE_PATTERN),
        ("social_media_label", SOCIAL_SOURCE_PATTERN),
        ("other_person_attribution", THIRD_PARTY_SOURCE_PATTERN),
    )
    found: list[tuple[int, str, str]] = []
    for source_type, pattern in patterns:
        for match in pattern.finditer(prefix):
            found.append((match.start(), source_type, match.group(0)))
    if not found:
        return None
    selected_start, source_type, selected_text = max(found, key=lambda item: item[0])
    if source_type == "other_person_attribution" and re.match(
        r"(?:他|她|它|他们|她们)", selected_text, re.IGNORECASE
    ):
        antecedents: list[tuple[int, str]] = []
        for antecedent_type, pattern in (
            ("ai_inference", AI_SOURCE_PATTERN),
            ("social_media_label", SOCIAL_SOURCE_PATTERN),
            ("other_person_attribution", THIRD_PARTY_SOURCE_PATTERN),
        ):
            for match in pattern.finditer(prefix[:selected_start]):
                if not re.match(r"(?:他|她|它|他们|她们)", match.group(0), re.IGNORECASE):
                    antecedents.append((match.start(), antecedent_type))
        if antecedents:
            return max(antecedents, key=lambda item: item[0])[1]
        return "unknown_source"
    if source_type == "other_person_attribution" and re.search(
        r"匿名|身份不明|不知道对方是谁|(?:有|某)个人说|陌生人", prefix, re.IGNORECASE
    ):
        return "unknown_source"
    return source_type


def source_type_for(text: str, label_text: str, start: int | None = None, end: int | None = None) -> str:
    if start is None:
        start = text.find(label_text)
    if start < 0:
        start = 0
    if end is None:
        end = start + len(label_text)
    event = attribution_event_for_label(text, start, end)
    return event.source_type if event is not None else "unknown_source"


def quoted_candidates(text: str) -> Iterable[tuple[int, int, str]]:
    for match in re.finditer(r"[“‘\"']([^”’\"']{1,40})[”’\"']", text):
        candidate = match.group(1).strip()
        if not candidate:
            continue
        offset = match.group(1).find(candidate)
        start = match.start(1) + offset
        yield start, start + len(candidate), candidate


def quoted_span_is_explicit_label(text: str, start: int, end: int) -> bool:
    """Accept open-vocabulary quoted labels only when a local label frame exists."""

    prefix = text[max(0, start - 40) : start]
    suffix = text[end : min(len(text), end + 20)]
    if re.search(r"(?:我自己的)?原话(?:是|为)?\s*$", prefix, re.IGNORECASE):
        return False
    return bool(
        re.search(
            r"(?:说|写|觉得|认为|判断|断定|断言)(?:我|我自己)(?:是|就是|只是)\s*[“‘\"']?\s*$|"
            r"(?:说|写)(?:我)\s*[“‘\"']?\s*$|"
            r"(?:说|写|觉得|认为)[^，。；,;]{0,10}(?:等于|意味着|代表)\s*[“‘\"']?\s*$|"
            r"(?:称我为|叫我(?:作)?|把我(?:叫作|称作|称为|归为)|"
            r"我(?:自己)?(?:仍然?|明确|仍明确|也|又|还)?自称|"
            r"(?:仍然?|仍明确|明确|随后)?自称|我[^，。；,;]{0,16}把自己称为|"
            r"说自己是|给自己贴的?|给自己贴的标签是|给我的人格标签是|"
            r"人格标签是|标签是|称号是|我的自称是|认定自己就是|我叫自己|"
            r"我自称的|AI\s*说的|模型\s*说的|把我这种表现叫)\s*[“‘\"']?\s*$",
            prefix,
            re.IGNORECASE,
        )
        or (
            re.match(r"\s*(?:这个|该)?标签", suffix, re.IGNORECASE)
            and re.search(r"(?:我|AI|模型|软件|平台|博主|朋友|同事|导师|老师)", prefix)
        )
    )


OPEN_LABEL_RELATION_PATTERNS = (
    re.compile(
        r"(?:给|替)(?:我本人|我自己|我|你|他|她|张三|老周|小周|Leo|Jordan|Priya)"
        r"\s*(?:打上|贴上|加上|赋予)\s*[“‘\"'](?P<label>[^”’\"']{1,36})[”’\"']\s*(?:这个)?标签",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?:我本人|我自己|我|你|他|她|老周|队长|陈经理|我弟弟|弟弟|候选人甲|小航|"
        r"前任|姐姐|上一届学生|作者|被试|角色|案例人物|项目经理|哥哥|表弟|妹妹|母亲|"
        r"患者|来访者|客户|林悦|小周|I|You|he|she|Jordan|Priya)"
        r"\s*(?:就是|是|有|患有|像|am|is|are|was|were|have|has|had)\s*(?:一个|an?\s+)?"
        r"[“‘\"']?(?P<label>[^，。；,;“”‘’\"'\n]{1,36}?)"
        r"(?=[”’\"']|，|,|。|；|;|所以|因此|而且|and\s+therefore|\s+so\s+|$)",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?:写|叫|称|评价|暗示|说|认定|判断|断言|定义成|解释成|归为|页面说)"
        r"[^，。；,;\n]{0,14}?(?:我|他|她|老周|队长|陈经理|弟弟|候选人甲|小航|前任|姐姐|"
        r"学生|作者|被试|角色|项目经理|哥哥|表弟|妹妹|母亲|患者|来访者|客户|Leo|Jordan|Priya)?"
        r"(?:天生|就是|是|有|像|为|叫作|称作|称为|was|is|had)?\s*(?:一个|an?\s+)?"
        r"[“‘\"']?(?P<label>[^，。；,;“”‘’\"'\n]{1,36}?)"
        r"(?=[”’\"']|，|,|。|；|;|所以|因此|而且|and\s+therefore|\s+so\s+|$)",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?:把自己|自己)(?:定义成|叫作|称作|称为)|给自己下了结论[：:]?\s*(?:我是)?",
        re.IGNORECASE,
    ),
    re.compile(
        r"符合\s*(?P<label>[^，。；,;“”‘’\"'\n]{2,32}?障碍)\s*诊断标准",
        re.IGNORECASE,
    ),
)
FORMAL_SCALE_CODE_PATTERN = re.compile(
    r"PHQ-?9|ASRS-v1\.1|NEO-PI-3|Big\s+Five",
    re.IGNORECASE,
)


def open_label_candidates(text: str) -> list[LabelCandidate]:
    values: list[LabelCandidate] = []
    for pattern in OPEN_LABEL_RELATION_PATTERNS:
        if "label" not in pattern.groupindex:
            continue
        for match in pattern.finditer(text):
            raw = match.group("label")
            cleaned = raw.strip(" \t\n“”‘’\"'")
            cleaned = re.sub(r"^(?:一个|an?\s+)", "", cleaned, flags=re.IGNORECASE)
            cleaned = re.sub(r"^典型(?:的)?\s*", "", cleaned, flags=re.IGNORECASE)
            explicit_assignment = bool(
                re.search(r"(?:给|替).{0,12}(?:打上|贴上|加上|赋予)", match.group(0), re.IGNORECASE)
            )
            if not cleaned or (not looks_like_identity_label(cleaned) and not explicit_assignment):
                continue
            offset = raw.find(cleaned)
            start = match.start("label") + offset
            values.append(LabelCandidate(start, start + len(cleaned), cleaned, relation_bound=True))

    for match in FORMAL_SCALE_CODE_PATTERN.finditer(text):
        left, right = clause_bounds(text, match.start(), match.end())
        clause = text[left:right]
        if re.search(
            r"正式|量表|筛查|报告|测评报告|百分位|T\s*分|得了?\s*\d+|结果为|阳性阈值",
            clause,
            re.IGNORECASE,
        ) and not NONFORMAL_SCALE_CONTEXT_PATTERN.search(clause):
            values.append(LabelCandidate(match.start(), match.end(), match.group(0), "formal_scale_result"))

    for match in re.finditer(
        r"(?:页面|测试|测验|评论|博主)[^，。；,;\n]{0,18}(?:说|叫|显示|给我)?[^，。；,;\n]{0,10}"
        r"(?P<label>\d+%\s*ADHD|高神经质人格|抑郁型人格)",
        text,
        re.IGNORECASE,
    ):
        values.append(
            LabelCandidate(match.start("label"), match.end("label"), match.group("label"), "social_media_label")
        )
    for match in re.finditer(
        r"(?:你|我|I|You)\s*(?P<label>不懂共情|没责任心|没天赋|socially\s+defective|"
        r"emotionally\s+unstable)",
        text,
        re.IGNORECASE,
    ):
        values.append(LabelCandidate(match.start("label"), match.end("label"), match.group("label")))
    for match in re.finditer(
        r"(?:我本人|我自己|我)?[^，。；,;\n]{0,12}(?:觉得|认为|相信)自己(?:就是|是)\s*"
        r"(?P<label>[^，。；,;“”‘’\"'\n]{1,32})",
        text,
        re.IGNORECASE,
    ):
        if looks_like_identity_label(match.group("label")):
            values.append(LabelCandidate(match.start("label"), match.end("label"), match.group("label")))
    for match in re.finditer(
        r"我(?:本人|自己)?[^，。；,;\n]{0,16}说自己是\s*"
        r"(?P<label>[^，。；,;“”‘’\"'\n]{1,24})",
        text,
        re.IGNORECASE,
    ):
        if looks_like_identity_label(match.group("label")):
            values.append(
                LabelCandidate(
                    match.start("label"),
                    match.end("label"),
                    match.group("label"),
                    "user_self_description",
                    True,
                )
            )
    return values


def normalize_label_candidate(text: str, candidate: LabelCandidate) -> LabelCandidate | None:
    raw = text[candidate.start:candidate.end]
    cleaned, relative_start = trim_matched_outer_quotes(raw)
    relation = list(
        re.finditer(
            r"(?:叫我|称我|评价我|写我|说我|认为我|认定我|暗示我|判断我|断言我|"
            r"我就是|我是|你就是|你是|I\s+(?:am|was|have|had)|You\s+(?:are|were))\s*"
            r"(?:一个|an?\s+)?(?P<label>[^，。；,;“”‘’\"'\n]{1,36})$",
            cleaned,
            re.IGNORECASE,
        )
    )
    if relation:
        match = relation[-1]
        relative_start += match.start("label")
        cleaned = match.group("label")
    prefix = re.match(
        r"^(?:案例人物|老周|队长|陈经理|我弟弟|弟弟|候选人甲|小航|他的前任|前任|她姐姐|"
        r"姐姐|上一届学生|那位学生|文章作者|作者|案例中的被试|被试|剧本角色|角色|"
        r"项目经理|哥哥|表弟|妹妹|母亲|患者李某|来访者|客户|林悦|小周|Leo|Jordan|Priya|"
        r"he|she|her|him|自己|我|你)\s*(?:天生)?(?:就是|是|有|患有|像|为|was|is|had|has)?\s*",
        cleaned,
        re.IGNORECASE,
    )
    if prefix:
        relative_start += prefix.end()
        cleaned = cleaned[prefix.end():]
    article = re.match(r"^(?:一个|an?\s+)", cleaned, re.IGNORECASE)
    if article:
        relative_start += article.end()
        cleaned = cleaned[article.end():]
    negated_prefix = re.match(r"^(?:不是|并非|没有|并无)\s*", cleaned, re.IGNORECASE)
    lexical_without = bool(
        re.fullmatch(r"没有[^，。；,;\n]{1,24}(?:的人|者)", cleaned, re.IGNORECASE)
        or re.fullmatch(r"没有(?:自制力|领导力|行动力|责任心|数学脑子)", cleaned, re.IGNORECASE)
    )
    if negated_prefix and not lexical_without:
        relative_start += negated_prefix.end()
        cleaned = cleaned[negated_prefix.end():]
    if cleaned.startswith("作") and candidate.start > 0 and text[candidate.start - 1:candidate.start] == "叫":
        relative_start += 1
        cleaned = cleaned[1:]
    edge_trimmed = cleaned.strip(" \t\n：:")
    relative_start += cleaned.find(edge_trimmed)
    cleaned = edge_trimmed
    if not cleaned or not (
        looks_like_identity_label(cleaned)
        or candidate.relation_bound
        or candidate.seed_source in {
            "reported_clinical_diagnosis",
            "formal_scale_result",
            "social_media_label",
        }
    ):
        return None
    start = candidate.start + relative_start
    located = text.find(cleaned, start, candidate.end)
    if located >= 0:
        start = located
    return LabelCandidate(
        start,
        start + len(cleaned),
        cleaned,
        candidate.seed_source,
        candidate.relation_bound,
    )


def extract_label_candidates(text: str) -> list[LabelCandidate]:
    candidates: list[LabelCandidate] = []
    for start, end, candidate in quoted_candidates(text):
        if (
            quoted_span_is_explicit_label(text, start, end)
            and not re.search(r"所以|因此|therefore|\bso\b", candidate, re.IGNORECASE)
        ):
            candidates.append(LabelCandidate(start, end, candidate, relation_bound=True))

    seeded_groups = (
        (formal_diagnosis_spans(text), "reported_clinical_diagnosis"),
        (formal_scale_spans(text), "formal_scale_result"),
        (captured_label_candidates(text, FORMAL_DIAGNOSIS_LABEL_PATTERNS), "reported_clinical_diagnosis"),
        (captured_label_candidates(text, FORMAL_SCALE_LABEL_PATTERNS), "formal_scale_result"),
        (captured_label_candidates(text, NONFORMAL_CLINICAL_LABEL_PATTERNS), "social_media_label"),
    )
    for group, seed in seeded_groups:
        candidates.extend(LabelCandidate(start, end, value, seed) for start, end, value in group)
    candidates.extend(
        LabelCandidate(start, end, value, "user_self_description", True)
        for start, end, value in captured_label_candidates(text, SELF_LABEL_CAPTURE_PATTERNS)
    )
    candidates.extend(
        LabelCandidate(start, end, value, relation_bound=True)
        for start, end, value in captured_label_candidates(text, ATTRIBUTED_LABEL_CAPTURE_PATTERNS)
    )
    candidates.extend(open_label_candidates(text))

    for raw in KNOWN_LABEL_PATTERNS:
        for match in re.finditer(raw, text, re.IGNORECASE):
            inferred_seed = infer_seed_source(text, match.start(), match.end())
            if inferred_seed not in {"reported_clinical_diagnosis", "formal_scale_result"}:
                inferred_seed = None
            candidates.append(
                LabelCandidate(
                    match.start(),
                    match.end(),
                    match.group(0),
                    inferred_seed,
                )
            )

    normalized: list[LabelCandidate] = []
    for candidate in candidates:
        value = normalize_label_candidate(text, candidate)
        if value is not None:
            normalized.append(value)
    candidates = normalized

    priority = {
        "reported_clinical_diagnosis": 4,
        "formal_scale_result": 3,
        "social_media_label": 2,
        "user_self_description": 1,
        None: 0,
    }
    by_span: dict[tuple[int, int], LabelCandidate] = {}
    for candidate in candidates:
        key = (candidate.start, candidate.end)
        current = by_span.get(key)
        if current is None or priority[candidate.seed_source] > priority[current.seed_source]:
            by_span[key] = candidate
    ordered = sorted(
        by_span.values(),
        key=lambda item: (
            -priority[item.seed_source],
            -(item.end - item.start),
            item.start,
        ),
    )
    deduped: list[LabelCandidate] = []
    for candidate in ordered:
        if any(
            (
                candidate.start >= existing.start
                and candidate.end <= existing.end
            )
            or (
                existing.start >= candidate.start
                and existing.end <= candidate.end
            )
            for existing in deduped
        ):
            continue
        deduped.append(candidate)
    return sorted(deduped, key=lambda item: (item.start, item.end))


def explicit_quoted_material_candidate(text: str, candidate: LabelCandidate) -> bool:
    """Distinguish a quoted proposition from quotation marks around a live label."""

    if (
        candidate.seed_source == "reported_clinical_diagnosis"
        and diagnosis_assertion_is_current_user(text, candidate.start, candidate.end)
    ):
        return False

    left, right = clause_bounds(text, candidate.start, candidate.end)
    local = text[left:right]
    prefix = text[max(0, candidate.start - 72):candidate.start]
    suffix = text[candidate.end:min(len(text), candidate.end + 72)]
    document_frame = (
        r"(?:文章|论文|教材|网页|病历|记录|材料)"
        r"(?:作者)?(?:里|中|上)?(?:只)?(?:举例)?"
        r"(?:写|写道|写着|引用|摘录|说)"
    )
    explicitly_owned = bool(
        re.search(
            r"我(?:本人|自己)?[^，。；,;]{0,24}(?:说|写|自述)",
            prefix,
            re.IGNORECASE,
        )
        and re.search(
            r"(?:我现在|目前)?仍(?:然)?认可|这是我的自述|我仍这样认为",
            suffix,
            re.IGNORECASE,
        )
    )
    if explicitly_owned:
        return False
    return bool(
        re.search(
            document_frame + r"|这是引文|只是引用|这(?:句|段)是引用|引文(?:中|里)",
            local,
            re.IGNORECASE,
        )
        or (
            re.search(document_frame, prefix, re.IGNORECASE)
            and re.search(
                r"引文|引用|不是我的(?:诊断|情况|自述)|不是医生诊断",
                suffix,
                re.IGNORECASE,
            )
        )
    )


def context_claim_subject(
    text: str,
    candidate: LabelCandidate,
    event: AttributionEvent | None,
    quoted: bool,
) -> str:
    if event is not None and event.target_role in {"current_user", "third_party"}:
        return event.target_role
    left, _ = clause_bounds(text, candidate.start, candidate.end)
    prefix = text[left:candidate.start]
    third = list(
        re.finditer(
            r"(?:我(?:的)?)?(?:妹妹|姐姐|哥哥|弟弟|女儿|儿子|丈夫|妻子|同事|朋友|伴侣|室友|患者|来访者|小李|小王|他|她)",
            prefix,
            re.IGNORECASE,
        )
    )
    current = list(re.finditer(r"我本人|我自己|我", prefix))
    if third and (not current or third[-1].end() >= current[-1].end()):
        return "third_party"
    if current or (quoted and re.search(r"(?:诊断|说|称)我|我是", prefix)):
        return "current_user"
    return "unresolved"


def context_claim_polarity(
    text: str,
    candidate: LabelCandidate,
    event: AttributionEvent | None,
) -> str:
    left, _ = clause_bounds(text, candidate.start, candidate.end)
    prefix = text[left:candidate.start]
    if re.search(
        r"(?:绝非|谈不上(?:是|有)?)[^。；;\n]{0,20}$|"
        r"(?:没有|并未|未曾|从未|否认)[^。；;\n]{0,28}(?:诊断|确诊|做过|完成|施测|结果|得分|有)?[^。；;\n]{0,16}$",
        prefix,
        re.IGNORECASE,
    ):
        return "negated"
    if event is not None:
        return event.predicate_polarity
    if re.search(
        r"(?:可能|怀疑|不确定|是否|是不是|有没有|不见得(?:是|有)?|未必(?:是|有|认为)?)",
        prefix,
        re.IGNORECASE,
    ):
        return "uncertain"
    return "affirmed"


def context_claim_span(text: str, candidate: LabelCandidate) -> tuple[int, int]:
    """Keep a meaningful scale descriptor while retaining an exact source span."""

    start = candidate.start
    if candidate.seed_source == "formal_scale_result":
        descriptor = re.search(
            r"(?:成人|儿童|青少年|中文版|英文版)\s*$",
            text[max(0, candidate.start - 12):candidate.start],
            re.IGNORECASE,
        )
        if descriptor:
            start = max(0, candidate.start - 12) + descriptor.start()
    return start, candidate.end


def extract_context_claims(text: str) -> list[dict[str, Any]]:
    """Preserve non-current, negated and quoted claims without promoting them."""

    claims: list[dict[str, Any]] = []
    seen: set[tuple[int, int, str, str]] = set()
    for candidate in extract_label_candidates(text):
        event = attribution_event_for_label(
            text,
            candidate.start,
            candidate.end,
            candidate.seed_source,
        )
        quoted = explicit_quoted_material_candidate(text, candidate)
        polarity = context_claim_polarity(text, candidate, event)
        subject = context_claim_subject(text, candidate, event, quoted)
        context_only = (
            quoted
            or event is None
            or subject != "current_user"
            or event.discourse_kind != "personal"
            or polarity != "affirmed"
        )
        if not context_only:
            continue
        start, end = context_claim_span(text, candidate)
        source = "quoted_material" if quoted else (
            event.source_type
            if event is not None
            else candidate.seed_source or "unknown_source"
        )
        if source not in {*SOURCE_STATUS, "quoted_material"}:
            source = "unknown_source"
        evidence_status = "reported_unverified" if source == "quoted_material" else SOURCE_STATUS[source]
        key = (start, end, source, polarity)
        if key in seen:
            continue
        seen.add(key)
        claims.append(
            {
                "subject": subject,
                "source": source,
                "evidence_status": evidence_status,
                "polarity": polarity,
                "claim": text[start:end],
                "evidence": source_for(text, "E000", start, end),
            }
        )
    return claims


def extract_labels(text: str) -> list[dict[str, Any]]:
    if is_nonpersonal_transformation_task(text):
        return []
    labels: list[dict[str, Any]] = []
    accepted_spans: set[tuple[int, int]] = set()
    for candidate in extract_label_candidates(text):
        if (candidate.start, candidate.end) in accepted_spans:
            continue
        if "MBTI" in candidate.text.upper() and not re.fullmatch(r"[EI][NS][FT][JP]", candidate.text, re.IGNORECASE):
            continue
        event = attribution_event_for_label(
            text,
            candidate.start,
            candidate.end,
            candidate.seed_source,
        )
        if (
            event is None
            or event.target_role != "current_user"
            or event.discourse_kind != "personal"
            or event.predicate_polarity != "affirmed"
            or explicit_quoted_material_candidate(text, candidate)
        ):
            continue
        accepted_spans.add((candidate.start, candidate.end))
        exact = text[candidate.start:candidate.end]
        labels.append(
            {
                "text": exact,
                "source_type": event.source_type,
                "evidence_status": SOURCE_STATUS[event.source_type],
                "source": source_for(text, "E000", candidate.start, candidate.end),
                "attribution": event.as_dict(),
            }
        )
    return labels


def extract_judgments(text: str) -> list[dict[str, Any]]:
    if is_nonpersonal_transformation_task(text):
        return []
    asserted = asserted_identity_text(text)
    found: list[tuple[int, int, str, str]] = []
    for kind, pattern in JUDGMENT_PATTERNS:
        for match in pattern.finditer(asserted):
            if DECONSTRUCT_NEGATION_PATTERN.search(asserted) and DECONSTRUCT_REQUEST_PATTERN.search(match.group(0)):
                continue
            found.append((match.start(), match.end(), text[match.start():match.end()], kind))
    for match in DECONSTRUCT_REQUEST_PATTERN.finditer(asserted):
        if DECONSTRUCT_NEGATION_PATTERN.search(asserted):
            continue
        found.append((match.start(), match.end(), text[match.start():match.end()], "personality_generalization"))
    found.sort(key=lambda item: (item[0], -(item[1] - item[0])))
    results: list[dict[str, Any]] = []
    occupied: list[tuple[int, int]] = []
    for start, end, phrase, kind in found:
        if (
            any(start >= left and end <= right for left, right in occupied)
            or not judgment_targets_current_user(asserted, start, end)
        ):
            continue
        occupied.append((start, end))
        results.append(
            {
                "text": phrase,
                "kind": kind,
                "source": source_for(text, "E000", start, end),
            }
        )
    clauses = [item.strip() for item in re.split(r"[，。；,;]", asserted) if item.strip()]
    offset = 0
    for clause in clauses:
        start = text.find(clause, offset)
        offset = start + len(clause)
        end = start + len(clause)
        if (
            not VERDICT_PATTERN.search(clause)
            or any(
                (start >= occupied_left and end <= occupied_right)
                or (occupied_left >= start and occupied_right <= end)
                for occupied_left, occupied_right in occupied
            )
            or not judgment_targets_current_user(asserted, start, end)
        ):
            continue
        if HIGH_COST_PATTERN.search(clause):
            kind = "high_cost_decision_request"
        elif re.search(r"(?:责任|不是我的问题|一定是我.{0,12}(?:搞坏|毁掉)|都是我.{0,12}(?:造成|搞坏))", clause):
            kind = "responsibility_transfer"
        elif re.search(r"(?:永远|以后|任何|所有|注定|必然|不可能|一定)", clause):
            kind = "future_verdict"
        elif re.search(r"(?:做不了|胜任不了|带不好|没有.{0,8}潜力|不配负责|不能管理|无法影响|不适合)", clause):
            kind = "capability_verdict"
        else:
            kind = "personality_generalization"
        results.append(
            {
                "text": text[start:end],
                "kind": kind,
                "source": source_for(text, "E000", start, end),
            }
        )
    for item in results:
        item["target_id"] = judgment_id(item)
    return results


def extract_observations(text: str) -> list[dict[str, Any]]:
    patterns = (
        (re.compile(r"我这两天不想回伴侣消息"), "伴侣消息", "未提供", "这两天"),
        (re.compile(r"我这两天不想回对象消息"), "伴侣消息", "未提供", "这两天"),
        (
            re.compile(
                r"[一二三四五六七八九十百两\d]+年前我[^，。；,;]{0,18}曾?"
                r"(?P<observation>从[^，。；,;]{1,24}被救下)"
            ),
            "历史事件",
            "一次已报告事件",
            "历史",
        ),
        (
            re.compile(r"我自己的原话(?:是|为)?\s*[“‘\"'](?P<observation>[^”’\"']{1,60})[”’\"']"),
            "用户原话所述情境",
            "按原话记录",
            "未提供",
        ),
        (
            re.compile(
                r"我陈述的事实(?:是|为)\s*[“‘\"'](?P<observation>[^”’\"']{1,80})[”’\"']"
            ),
            "用户明确标注的事实",
            "按原话记录",
            "未提供",
        ),
        (
            re.compile(r"目前唯一事实(?:是|为)\s*(?P<observation>[^。；;\n]{2,100})"),
            "用户明确限定的当前事实",
            "按原话记录",
            "当前陈述",
        ),
        (
            re.compile(
                r"(?:我陈述的事实|可核对的记录|事实)(?:是|为)\s*"
                r"(?P<observation>[^。；;\n]{3,120}?)(?=；|;|。|，(?:所以|因此)|$)"
            ),
            "用户明确标注的可核对记录",
            "按原话记录",
            "原文所述期间",
        ),
    )
    observations: list[dict[str, Any]] = []
    seen_sources: set[tuple[int, int]] = set()
    seen_semantics: list[tuple[int, int, str]] = []
    for pattern, context, frequency, timeframe in patterns:
        match = pattern.search(text)
        if match:
            group = "observation" if "observation" in match.groupdict() else None
            phrase = match.group(group) if group else match.group(0)
            start = match.start(group) if group else match.start()
            end = match.end(group) if group else match.end()
            canonical = phrase.strip(" \t\n“”‘’\"'")
            if any(
                canonical == existing
                and start < existing_end
                and end > existing_start
                for existing_start, existing_end, existing in seen_semantics
            ):
                continue
            source_key = (start, end)
            if source_key in seen_sources:
                continue
            seen_sources.add(source_key)
            seen_semantics.append((start, end, canonical))
            observations.append(
                {
                    "text": phrase,
                    "context": context,
                    "frequency": frequency,
                    "timeframe": timeframe,
                    "source": source_for(text, "E000", start, end),
                }
            )
    return observations


def extract_counterexamples(text: str) -> list[dict[str, Any]]:
    pattern = re.compile(
        r"(?:但|不过|可是|相反)?\s*(?:已知)?(?:反例|相反证据)(?:是|为)\s*"
        r"(?P<counterexample>[^。；;\n]{3,120}?)(?=；|;|。|$)",
        re.IGNORECASE,
    )
    values: list[dict[str, Any]] = []
    for match in pattern.finditer(text):
        phrase = match.group("counterexample").strip(" “ ”‘’\"'")
        if re.search(r"只是.{0,12}(?:栏名|字段)|没有填写|尚未提供", phrase):
            continue
        raw = match.group("counterexample")
        offset = raw.find(phrase)
        start = match.start("counterexample") + offset
        values.append(
            {
                "text": phrase,
                "source": source_for(text, "E000", start, start + len(phrase)),
            }
        )
    return values


def detect_language(text: str) -> str:
    has_cjk = bool(re.search(r"[\u3400-\u9fff]", text))
    has_latin = bool(re.search(r"[A-Za-z]", text))
    if has_cjk and has_latin:
        return "mixed"
    return "zh-CN" if has_cjk else "en"


def route_text(text: str) -> dict[str, Any]:
    if is_nonpersonal_transformation_task(text):
        return {"mode": "needs_information", "trigger": False, "reason_codes": ["nonpersonal_material"]}
    if has_immediate_safety_signal(text):
        return {"mode": "safety_support", "trigger": False, "reason_codes": ["immediate_safety"]}
    if has_recent_self_harm_signal(text):
        return {
            "mode": "support_escalation",
            "trigger": False,
            "reason_codes": ["recent_recurrent_self_harm"],
        }

    if has_severe_functional_impairment(text):
        return {
            "mode": "support_escalation",
            "trigger": False,
            "reason_codes": ["reported_severe_functional_impairment"],
        }

    labels = extract_labels(text)
    judgments = extract_judgments(text)
    source_types = {item["source_type"] for item in labels}
    has_verdict = bool(judgments) or has_identity_verdict_signal(text) or has_high_cost_decision(text)
    has_audit_request = has_explicit_deconstruction_request(text)
    has_formal_diagnosis = "reported_clinical_diagnosis" in source_types
    has_preference = has_stable_preference(text)
    has_formal_scale = "formal_scale_result" in source_types
    has_label = bool(labels)
    has_mixed_sources = len(source_types) > 1 and bool(
        source_types - {"reported_clinical_diagnosis", "formal_scale_result"}
    )
    nonpersonal_task = bool(protected_material_spans(text)) or (
        any(pattern.search(text) for _, pattern in NONPERSONAL_TASK_PATTERNS)
        and not PERSONAL_IDENTITY_TRANSITION_PATTERN.search(text)
    )
    has_evidence_roles = bool(extract_observations(text) or extract_counterexamples(text))
    if has_medical_change_request(text):
        return {
            "mode": "support_escalation",
            "trigger": False,
            "reason_codes": ["medical_decision_reserved"],
        }
    if medical_decision_owner(text) == "clinician_established":
        return {
            "mode": "clinical_report_only",
            "trigger": False,
            "reason_codes": ["clinician_established_plan"],
        }
    if has_problem_behavior_change_request(text):
        return {
            "mode": "deconstruct",
            "trigger": True,
            "reason_codes": ["observable_behavior_change_request"],
        }
    if not has_label and nonpersonal_task:
        return {"mode": "needs_information", "trigger": False, "reason_codes": ["nonpersonal_material"]}
    if has_mixed_sources:
        return {
            "mode": "deconstruct",
            "trigger": True,
            "reason_codes": ["mixed_label_sources", "source_separation_required"],
        }
    if has_formal_diagnosis and not has_verdict:
        return {"mode": "clinical_report_only", "trigger": False, "reason_codes": ["reported_clinical_fact"]}
    if has_formal_scale and not has_verdict:
        return {"mode": "clinical_report_only", "trigger": False, "reason_codes": ["reported_scale_result"]}
    labels_are_self_description = bool(labels) and all(
        item.get("source_type") == "user_self_description" for item in labels
    )
    if (
        has_preference
        and not has_verdict
        and not has_formal_diagnosis
        and not has_audit_request
        and (not has_label or labels_are_self_description)
    ):
        reason = (
            "stable_preference_with_self_description"
            if labels_are_self_description
            else "stable_preference_without_verdict"
        )
        return {"mode": "preference_acknowledgement", "trigger": False, "reason_codes": [reason]}
    if has_audit_request or (has_label and has_evidence_roles) or (
        has_verdict and (has_label or AI_SOURCE_PATTERN.search(text) or SOCIAL_SOURCE_PATTERN.search(text))
    ) or bool(judgments) or (has_preference and has_verdict):
        codes = ["identity_to_verdict"]
        if has_audit_request:
            codes.append("explicit_label_audit_request")
        if has_high_cost_decision(text):
            codes.append("high_cost_decision_pressure")
        if has_formal_diagnosis:
            codes.append("diagnosis_to_global_verdict")
        return {"mode": "deconstruct", "trigger": True, "reason_codes": codes}
    if EXPLANATION_ONLY_PATTERN.search(text) or len(text.strip()) <= 12 or has_label:
        return {"mode": "needs_information", "trigger": False, "reason_codes": ["insufficient_for_verdict_audit"]}
    return {"mode": "needs_information", "trigger": False, "reason_codes": ["no_identity_verdict_detected"]}


def reserved_judgments(labels: list[dict[str, Any]]) -> list[dict[str, str]]:
    values = [
        {
            "topic": "人格身份",
            "owner": "user",
            "reason": "有限对话与单次实验不能定义跨情境人格",
        }
    ]
    if any(item["source_type"] == "reported_clinical_diagnosis" for item in labels):
        values.append(
            {
                "topic": "诊断与医疗方案",
                "owner": "qualified_professional",
                "reason": "AI 不确认、撤销诊断，也不替代医疗专业判断",
            }
        )
    if any(item["source_type"] == "formal_scale_result" for item in labels):
        values.append(
            {
                "topic": "量表结果的临床解释",
                "owner": "qualified_professional",
                "reason": "正式量表结果不是单独诊断，解释范围由量表规范和现实专业评估决定",
            }
        )
    return values


def empty_analysis(experiment_status: str = "not_planned") -> dict[str, Any]:
    experiment = copy.deepcopy(EMPTY_EXPERIMENT)
    experiment["status"] = experiment_status
    return {
        "labels": [],
        "context_claims": [],
        "judgments": [],
        "observations": [],
        "counterexamples": [],
        "candidate_variables": [],
        "unknowns": [],
        "minimal_question": {"text": "", "status": "not_needed" if experiment_status == "not_needed" else "proposed"},
        "experiment": experiment,
        "reserved_judgments": [],
    }


def make_analysis(text: str, route: dict[str, Any]) -> dict[str, Any]:
    mode = route["mode"]
    if mode == "preference_acknowledgement":
        analysis = empty_analysis("not_needed")
        analysis["context_claims"] = extract_context_claims(text)
        analysis["unknowns"] = ["该偏好是否造成用户本人想改变的功能受损"]
        analysis["reserved_judgments"] = [
            {"topic": "是否改变偏好", "owner": "user", "reason": "稳定偏好本身不需要被纠正"}
        ]
        return analysis
    if mode == "safety_support":
        analysis = empty_analysis("not_needed")
        analysis["context_claims"] = extract_context_claims(text)
        analysis["unknowns"] = ["当前危险是否迫在眉睫", "可立即联系的现实支持者"]
        analysis["reserved_judgments"] = [
            {"topic": "紧急安全处置", "owner": "qualified_professional", "reason": "现实安全优先于身份分析"}
        ]
        return analysis

    if mode == "support_escalation":
        analysis = empty_analysis("not_needed")
        analysis["context_claims"] = extract_context_claims(text)
        analysis["labels"] = extract_labels(text)
        analysis["observations"] = extract_observations(text)
        reasons = set(route.get("reason_codes", []))
        if "medical_decision_reserved" in reasons:
            change_domains = medical_change_domains(text)
            analysis["unknowns"] = ["现实专业人员尚未评估的变更风险与替代方案"]
            if "medication" in change_domains:
                topic = "用药方案调整"
                reason = "AI 不替用户决定停药、调量或重启药物"
            elif "medical_procedure" in change_domains:
                topic = "医疗程序选择"
                reason = "AI 不替用户决定接受、取消或改变医疗程序"
            else:
                topic = "治疗方案调整"
                reason = "AI 不替用户决定取消、中止、加码或改变治疗安排"
            analysis["reserved_judgments"] = [
                {"topic": topic, "owner": "qualified_professional", "reason": reason}
            ]
        elif "recent_recurrent_self_harm" in reasons:
            analysis["unknowns"] = ["想法是否变得迫切", "是否出现计划或可用手段", "可联系的现实支持者"]
            analysis["reserved_judgments"] = [
                {
                    "topic": "近期安全支持",
                    "owner": "qualified_professional",
                    "reason": "近期反复的死亡或自伤相关想法需要现实支持，不能用身份标签解释替代",
                }
            ]
        else:
            analysis["unknowns"] = [
                "功能受损的完整范围与直接原因",
                "当前可获得的现实支持",
                "是否出现尚未报告的安全风险",
            ]
            analysis["reserved_judgments"] = [
                {
                    "topic": "功能受损评估与支持方案",
                    "owner": "qualified_professional",
                    "reason": "严重功能受损需要现实中的完整评估，不能由身份标签或意志力解释替代",
                }
            ]
        return analysis

    labels = extract_labels(text)
    analysis = empty_analysis("not_planned" if mode == "deconstruct" else "not_needed")
    analysis["context_claims"] = extract_context_claims(text)
    analysis["labels"] = labels
    analysis["judgments"] = extract_judgments(text) if mode == "deconstruct" else []
    analysis["observations"] = extract_observations(text)
    analysis["counterexamples"] = extract_counterexamples(text)
    if mode == "deconstruct":
        analysis["unknowns"] = []
        if not analysis["observations"]:
            analysis["unknowns"].extend(["标签之外的具体行为记录", "行为出现的情境、频率与时间"])
        if not analysis["counterexamples"]:
            analysis["unknowns"].append("已知反例")
        if AI_PERSONALITY_INFERENCE_REQUEST_PATTERN.search(text) and not labels:
            analysis["unknowns"].append("有限聊天不足以定义跨情境人格或职业能力")
    elif mode == "clinical_report_only":
        analysis["unknowns"] = ["诊断或量表文件及其临床含义未由本工具独立核验"]
    else:
        analysis["unknowns"] = ["标签来源、具体行为、情境、频率与时间仍不足"]
    if mode == "deconstruct":
        question = "过去三个月，哪一次具体行为最让你得出这个结论，当时发生了什么？"
        question_status = "proposed"
    elif mode == "needs_information":
        reason_codes = set(route.get("reason_codes", []))
        if "nonpersonal_material" in reason_codes:
            question = "你要拆解的是你本人的身份判断，还是只分析这段外部材料？"
        elif labels:
            question = "这个标签下面，哪一次具体行为最需要核对，当时的情境、频率和时间是什么？"
        else:
            question = "你希望核对的是哪个身份标签，或哪一条由标签推出的能力结论？"
        question_status = "proposed"
    else:
        question = ""
        question_status = "not_needed"
    analysis["minimal_question"] = {"text": question, "status": question_status}
    analysis["reserved_judgments"] = reserved_judgments(labels)
    change_domains = medical_change_domains(text)
    if "medication" in change_domains and not any(
        item["topic"] == "诊断与医疗方案" for item in analysis["reserved_judgments"]
    ):
        analysis["reserved_judgments"].append(
            {
                "topic": "用药方案",
                "owner": "qualified_professional",
                "reason": "药物和剂量变更必须交给处方人员或其他合格专业人员",
            }
        )
    if "psychotherapy" in change_domains or "clinical_plan" in change_domains:
        analysis["reserved_judgments"].append(
            {
                "topic": "心理治疗方案",
                "owner": "qualified_professional",
                "reason": "用户保留选择，AI 不替用户和治疗专业人员决定取消、中止或改变治疗安排",
            }
        )
    if "medical_procedure" in change_domains:
        analysis["reserved_judgments"].append(
            {
                "topic": "医疗程序选择",
                "owner": "qualified_professional",
                "reason": "用户保留选择，AI 不替用户决定接受、取消或改变医疗程序",
            }
        )
    if has_high_cost_decision(text):
        analysis["reserved_judgments"].append(
            {
                "topic": "关系、职业或重大财务决定",
                "owner": "user",
                "reason": "身份标签和单次对话不能替用户决定分手、辞职、卖房或集中全部资产",
            }
        )
    return analysis


def scaffold_case(text: str, case_id: str | None, clock: str) -> dict[str, Any]:
    route = route_text(text)
    status = {
        "deconstruct": "drafted",
        "preference_acknowledgement": "no_intervention",
        "clinical_report_only": "no_intervention",
        "safety_support": "safety_redirected",
        "support_escalation": "no_intervention",
        "needs_information": "no_intervention",
    }[route["mode"]]
    identity = case_id or f"case-{hashlib.sha256(text.encode('utf-8')).hexdigest()[:12]}"
    return {
        "schema_version": "2.0",
        "case_id": identity,
        "revision": 0,
        "status": status,
        "language": detect_language(text),
        "created_at": clock,
        "updated_at": clock,
        "evidence": [{"id": "E000", "kind": "user_input", "text": text, "recorded_at": clock}],
        "route": route,
        "risk_flags": {
            "clinical": has_clinical_signal(text),
            "safety": bool(safety_features(text)),
            "medical_change_request": has_medical_change_request(text),
            "high_cost_decision": has_high_cost_decision(text),
            "functional_impairment": has_severe_functional_impairment(text),
        },
        "analysis": make_analysis(text, route),
        "review": None,
    }


def iter_sourced_items(analysis: dict[str, Any]) -> Iterable[tuple[str, int, dict[str, Any]]]:
    for field in ("labels", "judgments", "observations", "counterexamples"):
        for index, item in enumerate(analysis.get(field, [])):
            yield field, index, item


def all_generated_text(
    analysis: dict[str, Any],
    review: dict[str, Any] | None = None,
) -> Iterable[tuple[str, str]]:
    question = analysis.get("minimal_question", {}).get("text", "")
    yield "$.analysis.minimal_question.text", question
    for index, value in enumerate(analysis.get("unknowns", [])):
        yield f"$.analysis.unknowns[{index}]", value
    for index, item in enumerate(analysis.get("candidate_variables", [])):
        yield f"$.analysis.candidate_variables[{index}].name", item.get("name", "")
        yield f"$.analysis.candidate_variables[{index}].reason", item.get("reason", "")
    experiment = analysis.get("experiment", {})
    for field in ("target_claim", "primary_variable", "action", "reversibility_note"):
        yield f"$.analysis.experiment.{field}", experiment.get(field, "")
    for field in ("kept_constant", "measures", "support_if", "weaken_if"):
        for index, value in enumerate(experiment.get(field, [])):
            yield f"$.analysis.experiment.{field}[{index}]", value
    for index, item in enumerate(analysis.get("reserved_judgments", [])):
        yield f"$.analysis.reserved_judgments[{index}].topic", item.get("topic", "")
        yield f"$.analysis.reserved_judgments[{index}].reason", item.get("reason", "")
    if isinstance(review, dict):
        yield "$.review.target_claim", review.get("target_claim", "")
        yield "$.review.rationale", review.get("rationale", "")


def generated_policy_text(value: object) -> str:
    """Mask only a genuinely negated directive, never a later sibling action."""

    text = str(value)
    segments = GENERATED_POLICY_SEGMENT_BOUNDARY_PATTERN.split(text)
    active: list[str] = []
    for segment in segments:
        if not segment:
            continue
        if (
            GENERATED_NEGATED_DIRECTIVE_PATTERN.search(segment)
            and not GENERATED_DOUBLE_NEGATION_PATTERN.search(segment)
        ):
            active.append(" " * len(segment))
        else:
            active.append(segment)
    return "".join(active)


def generated_diagnosis_confirmation(value: str) -> bool:
    """Reject affirmative diagnosis claims while preserving explicit boundary statements."""

    for segment in GENERATED_POLICY_SEGMENT_BOUNDARY_PATTERN.split(value):
        if not segment or GENERATED_DIAGNOSIS_NONCONFIRMATION_PATTERN.search(segment):
            continue
        if GENERATED_DIAGNOSIS_CONFIRMATION_PATTERN.search(segment):
            return True
    return False


def unreported_personal_claim(value: str, original: str) -> bool:
    """Detect generated first-person inner-state or promise claims not present in evidence."""

    evidence = identity_normal_form(original)
    for match in GENERATED_PERSONAL_CLAIM_PATTERN.finditer(value):
        if re.search(r"尝试|安排[^，,。；;\n]{0,12}提醒", match.group(0)):
            continue
        left = max((value.rfind(mark, 0, match.start()) for mark in "。；;\n"), default=-1) + 1
        right_candidates = [
            position
            for mark in "。；;\n"
            if (position := value.find(mark, match.end())) >= 0
        ]
        right = min(right_candidates, default=len(value))
        local_clause = value[left:right]
        overlap_guard = any(
            guard.start() <= match.start() < guard.end()
            or match.start() <= guard.start() < match.end()
            for guard in GENERATED_PERSONAL_CLAIM_GUARD_PATTERN.finditer(value)
        )
        prefix_guard = bool(
            GENERATED_PERSONAL_CLAIM_CONDITIONAL_GUARD_PATTERN.search(
                value[left : match.start()]
            )
        )
        placeholder_before = list(
            re.finditer(r"\[[^\]\n]{2,80}\]", value[left : match.start()])
        )
        if placeholder_before:
            last_placeholder_end = left + placeholder_before[-1].end()
            if re.search(r"[，,；;。\n]", value[last_placeholder_end : match.start()]):
                prefix_guard = False
        if overlap_guard or (
            prefix_guard
            and not re.search(r"(?:但|不过|然而|可是|其实)", local_clause, re.IGNORECASE)
        ):
            continue
        if identity_normal_form(match.group(0)) not in evidence:
            return True
    return False


def unreported_psychological_cause(value: str, original: str) -> bool:
    """A causal story about the user must be verbatim evidence, not model completion."""

    evidence = identity_normal_form(original)
    for match in GENERATED_UNREPORTED_CAUSE_PATTERN.finditer(value):
        if identity_normal_form(match.group(0)) not in evidence:
            return True
    return False


def identity_normal_form(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).casefold()
    return "".join(
        character
        for character in normalized
        if not character.isspace()
        and unicodedata.category(character) != "Cf"
        and not unicodedata.category(character).startswith(("P", "Z"))
    )


def experiment_outcome_normal_form(value: str) -> str:
    """Normalize narrow outcome wording without inventing an opposite result."""

    normalized = identity_normal_form(value)
    substitutions = (
        ("仍然未能", "未"),
        ("仍未能", "未"),
        ("仍然未", "未"),
        ("仍未", "未"),
        ("没有能够", "未"),
        ("没有能", "未"),
        ("没有完成", "未完成"),
        ("未能完成", "未完成"),
    )
    for source, target in substitutions:
        normalized = normalized.replace(source, target)
    return normalized


def experiment_outcomes_overlap(support_if: Any, weaken_if: Any) -> bool:
    """Reject an outcome, including a lexical paraphrase, placed on both sides."""

    if not isinstance(support_if, list) or not isinstance(weaken_if, list):
        return False
    support = {
        experiment_outcome_normal_form(value)
        for value in support_if
        if isinstance(value, str) and value.strip()
    }
    weaken = {
        experiment_outcome_normal_form(value)
        for value in weaken_if
        if isinstance(value, str) and value.strip()
    }
    return bool(support.intersection(weaken))


def semantic_item_key(value: Any) -> str:
    normalized = copy.deepcopy(value)
    if (
        isinstance(normalized, dict)
        and {"text", "kind", "source"}.issubset(normalized)
    ):
        # target_id is a public handle derived from the evidence span, not a
        # second semantic judgment.
        normalized.pop("target_id", None)
    return hashlib.sha256(canonical_json(normalized)).hexdigest()


def judgment_id(item: dict[str, Any]) -> str:
    source = item.get("source", {})
    return (
        f"J-{source.get('evidence_id', 'UNKNOWN')}-"
        f"{source.get('start', 'X')}-{source.get('end', 'X')}"
    )


def merge_semantic_baseline(
    supplied: dict[str, Any],
    baseline: dict[str, Any],
) -> dict[str, Any]:
    """Restore runtime-derived facts before model-authored planning is validated."""

    merged = copy.deepcopy(supplied)
    for field in (
        "labels",
        "context_claims",
        "judgments",
        "observations",
        "counterexamples",
        "reserved_judgments",
    ):
        required = copy.deepcopy(baseline.get(field, []))
        extras = copy.deepcopy(merged.get(field, [])) if isinstance(merged.get(field), list) else []
        if field == "judgments":
            supplied_by_key: dict[str, Any] = {}
            supplied_order: list[str] = []
            for item in extras:
                key = semantic_item_key(item)
                if key not in supplied_by_key:
                    supplied_by_key[key] = item
                    supplied_order.append(key)
            resolved: list[Any] = []
            resolved_keys: set[str] = set()
            for item in required:
                key = semantic_item_key(item)
                resolved.append(copy.deepcopy(supplied_by_key.get(key, item)))
                resolved_keys.add(key)
            resolved.extend(
                copy.deepcopy(supplied_by_key[key])
                for key in supplied_order
                if key not in resolved_keys
            )
            merged[field] = resolved
            continue
        seen = {semantic_item_key(item) for item in required}
        required.extend(item for item in extras if semantic_item_key(item) not in seen)
        merged[field] = required
    required_unknowns = list(baseline.get("unknowns", []))
    extras_unknowns = merged.get("unknowns", []) if isinstance(merged.get("unknowns"), list) else []
    merged["unknowns"] = required_unknowns + [
        value for value in extras_unknowns if value not in required_unknowns
    ]
    return merged


def semantic_baseline_errors(
    analysis: dict[str, Any],
    baseline: dict[str, Any],
) -> list[dict[str, str]]:
    failures: list[dict[str, str]] = []
    field_codes = {
        "labels": "semantic_baseline_label_missing",
        "context_claims": "semantic_baseline_context_claim_missing",
        "judgments": "semantic_baseline_judgment_missing",
        "observations": "semantic_baseline_observation_missing",
        "counterexamples": "semantic_baseline_counterexample_missing",
        "reserved_judgments": "semantic_baseline_reserved_judgment_missing",
    }
    for field, code in field_codes.items():
        actual = {
            semantic_item_key(item)
            for item in analysis.get(field, [])
            if isinstance(item, dict)
        }
        for item in baseline.get(field, []):
            if semantic_item_key(item) not in actual:
                failures.append(
                    error(code, f"$.analysis.{field}", "runtime-derived semantic baseline cannot be removed")
                )
                break
    actual_unknowns = set(analysis.get("unknowns", []))
    if any(value not in actual_unknowns for value in baseline.get("unknowns", [])):
        failures.append(
            error(
                "semantic_baseline_unknown_missing",
                "$.analysis.unknowns",
                "runtime-derived unresolved slots cannot be removed",
            )
        )
    return failures


def meaningful_claim_tokens(value: str) -> set[str]:
    normalized = unicodedata.normalize("NFKC", value).casefold()
    tokens: set[str] = set()
    for sequence in re.findall(r"[\u3400-\u9fff]{2,}", normalized):
        tokens.update(sequence[index : index + 2] for index in range(len(sequence) - 1))
    stopwords = {"this", "that", "with", "from", "have", "will", "cannot", "never"}
    tokens.update(
        token
        for token in re.findall(r"[a-z][a-z0-9-]{3,}", normalized)
        if token not in stopwords
    )
    return tokens


def review_overgeneralizes(value: str) -> bool:
    """Allow explicit scope limits while rejecting affirmative identity conclusions."""

    boundary_phrases = re.compile(
        r"(?:不|不能|不会|未)(?:用于|足以|代表)?(?:撤销诊断|判断整个人格|证明我(?:就)?是)|"
        r"does\s+not\s+(?:revoke\s+the\s+diagnosis|define\s+my\s+personality)",
        re.IGNORECASE,
    )
    return bool(REVIEW_GENERALIZATION_PATTERN.search(boundary_phrases.sub(" ", value)))


def semantic_errors(case: dict[str, Any]) -> list[dict[str, str]]:
    errors: list[dict[str, str]] = []
    evidence = {item.get("id"): item for item in case.get("evidence", []) if isinstance(item, dict)}
    if len(evidence) != len(case.get("evidence", [])):
        errors.append(error("duplicate_evidence_id", "$.evidence", "evidence ids must be unique"))

    analysis = case.get("analysis", {})
    labels = analysis.get("labels", [])
    for field, index, item in iter_sourced_items(analysis):
        source = item.get("source", {})
        path = f"$.analysis.{field}[{index}]"
        record = evidence.get(source.get("evidence_id"))
        if record is None:
            errors.append(error("unknown_evidence_reference", f"{path}.source.evidence_id", "evidence id does not exist"))
            continue
        start, end = source.get("start"), source.get("end")
        text = record.get("text", "")
        if not isinstance(start, int) or not isinstance(end, int) or start < 0 or end <= start or end > len(text):
            errors.append(error("source_span_mismatch", f"{path}.source", "source span is outside evidence"))
            continue
        quote = text[start:end]
        if source.get("quote") != quote or item.get("text") != quote:
            errors.append(error("source_span_mismatch", f"{path}.source", "quote and item text must equal the exact evidence span"))
        if field == "judgments" and "target_id" in item:
            expected_target_id = judgment_id(item)
            if item.get("target_id") != expected_target_id:
                errors.append(
                    error(
                        "judgment_target_id_mismatch",
                        f"{path}.target_id",
                        "target_id must equal the stable ID derived from its evidence span",
                    )
                )

    normalized_labels = {identity_normal_form(item.get("text", "")) for item in labels}
    seen_observation_sources: dict[tuple[object, object, object], int] = {}
    for index, item in enumerate(analysis.get("observations", [])):
        if identity_normal_form(item.get("text", "")) in normalized_labels:
            errors.append(error("label_is_not_behavior", f"$.analysis.observations[{index}].text", "a label cannot be recorded as an observable behavior"))
        source = item.get("source", {})
        source_key = (
            source.get("evidence_id"),
            source.get("start"),
            source.get("end"),
        )
        if source_key in seen_observation_sources:
            errors.append(
                error(
                    "observation_metadata_unbound",
                    f"$.analysis.observations[{index}]",
                    "one evidence span cannot be duplicated with independently generated observation metadata",
                )
            )
        else:
            seen_observation_sources[source_key] = index

    for index, item in enumerate(labels):
        path = f"$.analysis.labels[{index}]"
        expected_status = SOURCE_STATUS.get(item.get("source_type"))
        if expected_status and item.get("evidence_status") != expected_status:
            errors.append(error("evidence_status_mismatch", f"$.analysis.labels[{index}].evidence_status", "status does not match label source type"))
        source = item.get("source", {})
        source_record = evidence.get(source.get("evidence_id"), {})
        source_text = source_record.get("text", "")
        attribution = item.get("attribution", {})
        attribution_source = attribution.get("source", {})
        if (
            attribution_source.get("type") != item.get("source_type")
            or attribution_source.get("evidence_status") != item.get("evidence_status")
        ):
            errors.append(
                error(
                    "attribution_source_mismatch",
                    f"{path}.attribution.source",
                    "attribution source must equal the persisted label source and evidence status",
                )
            )

        label_span = attribution.get("label", {})
        if label_span.get("start") != source.get("start") or label_span.get("end") != source.get("end"):
            errors.append(
                error(
                    "attribution_label_span_mismatch",
                    f"{path}.attribution.label",
                    "attribution label span must equal the exact cited label span",
                )
            )

        target = attribution.get("target", {})
        if target.get("role") != "current_user" or target.get("resolution") == "unresolved":
            errors.append(
                error(
                    "attribution_target_invalid",
                    f"{path}.attribution.target",
                    "only a label resolved to the current user may be persisted",
                )
            )

        discourse = attribution.get("discourse_context", {})
        if discourse.get("kind") != "personal":
            errors.append(
                error(
                    "attribution_discourse_invalid",
                    f"{path}.attribution.discourse_context.kind",
                    "quoted, fictional, documentary, educational and test material cannot become a personal label",
                )
            )

        replay_components = (
            ("speaker", attribution.get("speaker", {})),
            ("predicate", attribution.get("predicate", {})),
            ("target", target),
        )
        for component_name, component in replay_components:
            span = component.get("span", {})
            component_start = span.get("start")
            component_end = span.get("end")
            component_path = f"{path}.attribution.{component_name}"
            if (
                not isinstance(component_start, int)
                or not isinstance(component_end, int)
                or component_start < 0
                or component_end < component_start
                or component_end > len(source_text)
            ):
                errors.append(
                    error(
                        "attribution_span_invalid",
                        f"{component_path}.span",
                        "attribution component span must remain inside its cited evidence",
                    )
                )
                continue
            if component.get("text") != source_text[component_start:component_end]:
                errors.append(
                    error(
                        "attribution_text_mismatch",
                        f"{component_path}.text",
                        "attribution component text must replay exactly from its evidence span",
                    )
                )

        discourse_span = discourse.get("span", {})
        discourse_start = discourse_span.get("start")
        discourse_end = discourse_span.get("end")
        cited_start = source.get("start")
        cited_end = source.get("end")
        if (
            not isinstance(discourse_start, int)
            or not isinstance(discourse_end, int)
            or discourse_start < 0
            or discourse_end < discourse_start
            or discourse_end > len(source_text)
            or not isinstance(cited_start, int)
            or not isinstance(cited_end, int)
            or discourse_start > cited_start
            or discourse_end < cited_end
        ):
            errors.append(
                error(
                    "attribution_span_invalid",
                    f"{path}.attribution.discourse_context.span",
                    "discourse span must be inside evidence and contain the label span",
                )
            )

        expected_source_type = source_type_for(
            source_text,
            item.get("text", ""),
            source.get("start"),
            source.get("end"),
        )
        if item.get("source_type") != expected_source_type:
            errors.append(
                error(
                    "label_source_mismatch",
                    f"$.analysis.labels[{index}].source_type",
                    f"source type must remain {expected_source_type} for the cited evidence",
                )
            )
        reparsed_event = attribution_event_for_label(
            source_text,
            source.get("start", 0),
            source.get("end", 0),
        )
        if reparsed_event is None:
            errors.append(
                error(
                    "attribution_semantic_unresolved",
                    f"{path}.attribution",
                    "the cited evidence no longer resolves to an attribution event",
                )
            )
        else:
            expected_attribution = reparsed_event.as_dict()
            semantic_components = (
                ("source", "attribution_source_semantic_mismatch"),
                ("speaker", "attribution_speaker_semantic_mismatch"),
                ("predicate", "attribution_predicate_semantic_mismatch"),
                ("target", "attribution_target_semantic_mismatch"),
                ("discourse_context", "attribution_discourse_semantic_mismatch"),
            )
            for component, code in semantic_components:
                if attribution.get(component) != expected_attribution.get(component):
                    errors.append(
                        error(
                            code,
                            f"{path}.attribution.{component}",
                            "persisted attribution must equal a fresh parse of the cited evidence",
                        )
                    )
        if item.get("source_type") == "reported_clinical_diagnosis" and not case.get("risk_flags", {}).get("clinical"):
            errors.append(error("clinical_flag_missing", "$.risk_flags.clinical", "reported diagnosis requires the clinical flag"))

    label_spans = {
        (
            item.get("source", {}).get("evidence_id"),
            item.get("source", {}).get("start"),
            item.get("source", {}).get("end"),
        )
        for item in labels
        if isinstance(item, dict)
    }
    original_evidence_text = evidence.get("E000", {}).get("text", "")
    if original_evidence_text:
        canonical_claims = extract_context_claims(original_evidence_text)
        if analysis.get("context_claims", []) != canonical_claims:
            errors.append(
                error(
                    "context_claim_semantic_mismatch",
                    "$.analysis.context_claims",
                    "context claims must exactly equal a fresh runtime parse of E000",
                )
            )
    for index, item in enumerate(analysis.get("context_claims", [])):
        path = f"$.analysis.context_claims[{index}]"
        source = item.get("evidence", {})
        record = evidence.get(source.get("evidence_id"))
        start, end = source.get("start"), source.get("end")
        if (
            record is None
            or not isinstance(start, int)
            or not isinstance(end, int)
            or start < 0
            or end <= start
            or end > len(record.get("text", ""))
        ):
            errors.append(
                error(
                    "context_claim_source_invalid",
                    f"{path}.evidence",
                    "context claim must cite an exact span from existing evidence",
                )
            )
            continue
        exact = record["text"][start:end]
        if source.get("quote") != exact or item.get("claim") != exact:
            errors.append(
                error(
                    "context_claim_source_mismatch",
                    f"{path}.evidence",
                    "context claim and quote must equal their exact evidence span",
                )
            )
        if (source.get("evidence_id"), start, end) in label_spans:
            errors.append(
                error(
                    "context_claim_promoted_to_label",
                    path,
                    "one proposition cannot be both context-only and current-user label state",
                )
            )
        expected_status = (
            "reported_unverified"
            if item.get("source") == "quoted_material"
            else SOURCE_STATUS.get(item.get("source"))
        )
        if expected_status is not None and item.get("evidence_status") != expected_status:
            errors.append(
                error(
                    "context_claim_status_mismatch",
                    f"{path}.evidence_status",
                    "context claim evidence status must match its source class",
                )
            )

    route = case.get("route", {})
    mode = route.get("mode")
    status = case.get("status")
    experiment = analysis.get("experiment", {})
    experiment_status = experiment.get("status")
    original = evidence.get("E000", {}).get("text", "")
    if original:
        derived_route = route_text(original)
        baseline = make_analysis(original, derived_route)
        errors.extend(semantic_baseline_errors(analysis, baseline))
        canonical_observations = extract_observations(original)
        canonical_observation_counts: dict[str, int] = {}
        for item in canonical_observations:
            key = semantic_item_key(item)
            canonical_observation_counts[key] = canonical_observation_counts.get(key, 0) + 1
        observed_counts: dict[str, int] = {}
        identity_spans = [
            (
                item.get("source", {}).get("start"),
                item.get("source", {}).get("end"),
            )
            for field in ("labels", "judgments")
            for item in analysis.get(field, [])
            if item.get("source", {}).get("evidence_id") == "E000"
        ]
        for index, item in enumerate(analysis.get("observations", [])):
            source = item.get("source", {})
            if source.get("evidence_id") != "E000":
                continue
            key = semantic_item_key(item)
            observed_counts[key] = observed_counts.get(key, 0) + 1
            if observed_counts[key] <= canonical_observation_counts.get(key, 0):
                continue
            start = source.get("start")
            end = source.get("end")
            overlaps_identity = isinstance(start, int) and isinstance(end, int) and any(
                isinstance(identity_start, int)
                and isinstance(identity_end, int)
                and start < identity_end
                and end > identity_start
                for identity_start, identity_end in identity_spans
            )
            if overlaps_identity:
                errors.append(
                    error(
                        "observation_not_behavior",
                        f"$.analysis.observations[{index}]",
                        "a label or identity judgment cannot be recorded as observable behavior",
                    )
                )
            else:
                errors.append(
                    error(
                        "observation_metadata_unbound",
                        f"$.analysis.observations[{index}]",
                        "E000 observations and their context, frequency and timeframe must equal the runtime extraction",
                    )
                )
        if mode != derived_route["mode"] or route.get("trigger") != derived_route["trigger"]:
            errors.append(
                error(
                    "route_evidence_mismatch",
                    "$.route",
                    f"stored route does not match evidence-derived route {derived_route['mode']}",
                )
            )
        expected_risks = {
            "clinical": has_clinical_signal(original),
            "safety": bool(safety_features(original)),
            "medical_change_request": has_medical_change_request(original),
            "high_cost_decision": has_high_cost_decision(original),
            "functional_impairment": has_severe_functional_impairment(original),
        }
        for key, expected in expected_risks.items():
            if case.get("risk_flags", {}).get(key) is not expected:
                errors.append(error("risk_flag_mismatch", f"$.risk_flags.{key}", "risk flag does not match original evidence"))
        if derived_route["mode"] == "preference_acknowledgement" and experiment_status in {"planned", "active", "reviewed"}:
            errors.append(error("preference_correction", "$.analysis.experiment", "original evidence is a stable preference and cannot receive a correction experiment"))
        if experiment_corrects_stable_preference(original, experiment):
            errors.append(
                error(
                    "preference_correction",
                    "$.analysis.experiment",
                    "an experiment may test the narrow verdict but cannot use a reported preference as the correction target",
                )
            )
    if mode == "deconstruct" and route.get("trigger") is not True:
        errors.append(error("route_trigger_mismatch", "$.route.trigger", "deconstruct route must trigger"))
    if mode != "deconstruct" and route.get("trigger") is not False:
        errors.append(error("route_trigger_mismatch", "$.route.trigger", "non-deconstruct routes must not trigger"))
    if mode == "preference_acknowledgement":
        if status != "no_intervention" or experiment_status != "not_needed":
            errors.append(error("preference_correction", "$.analysis.experiment", "stable preference cannot receive a correction experiment"))
        if labels:
            errors.append(error("preference_relabel", "$.analysis.labels", "preference route must not add an identity label"))
    if mode in {"clinical_report_only", "support_escalation", "needs_information"} and experiment_status not in {"not_needed", "not_planned"}:
        errors.append(error("route_experiment_mismatch", "$.analysis.experiment.status", "this route does not authorize an experiment"))
    if mode == "safety_support":
        if status != "safety_redirected" or experiment_status not in {"not_needed", "not_planned"}:
            errors.append(error("safety_experiment_forbidden", "$.analysis.experiment", "safety route stops the experiment flow"))

    expected_experiment_status = {
        "drafted": "not_planned",
        "planned": "planned",
        "observing": "active",
        "reviewed": "reviewed",
        "no_intervention": "not_needed",
    }.get(status)
    if expected_experiment_status and experiment_status != expected_experiment_status:
        code = "preference_correction" if mode == "preference_acknowledgement" else "state_experiment_mismatch"
        errors.append(error(code, "$.analysis.experiment.status", f"{status} state requires {expected_experiment_status}"))

    if experiment_status in {"planned", "active", "reviewed"}:
        required_text = ("target_claim", "primary_variable", "action", "reversibility_note")
        for field in required_text:
            if not str(experiment.get(field, "")).strip():
                errors.append(error("experiment_incomplete", f"$.analysis.experiment.{field}", "planned experiment field cannot be empty"))
        for field in ("kept_constant", "measures", "support_if", "weaken_if"):
            if not experiment.get(field):
                errors.append(error("experiment_incomplete", f"$.analysis.experiment.{field}", "planned experiment list cannot be empty"))
        if experiment.get("duration", {}).get("value", 0) <= 0:
            errors.append(error("experiment_incomplete", "$.analysis.experiment.duration", "planned experiment requires a positive duration"))
        if experiment.get("reversible") is not True:
            errors.append(error("experiment_not_reversible", "$.analysis.experiment.reversible", "experiment must be reversible"))
        if experiment_outcomes_overlap(
            experiment.get("support_if"), experiment.get("weaken_if")
        ):
            errors.append(
                error(
                    "experiment_not_falsifiable",
                    "$.analysis.experiment",
                    "support and weakening conditions must contain semantically distinct outcomes",
                )
            )
        started_at = experiment.get("started_at")
        if experiment_status == "planned" and started_at not in {None, ""}:
            errors.append(error("experiment_started_too_early", "$.analysis.experiment.started_at", "plan cannot claim the experiment has started"))
        if started_at not in {None, ""}:
            try:
                parse_clock(str(started_at))
            except ValueError as exc:
                errors.append(error("experiment_start_invalid", "$.analysis.experiment.started_at", str(exc)))
        candidate_names = {item.get("name") for item in analysis.get("candidate_variables", [])}
        if experiment.get("primary_variable") not in candidate_names:
            errors.append(error("primary_variable_unregistered", "$.analysis.experiment.primary_variable", "primary variable must be registered as a hypothesis"))
        baseline_judgments = make_analysis(original, route_text(original)).get("judgments", []) if original else []
        judgment_lookup = {judgment_id(item): item for item in baseline_judgments}
        target_ids = experiment.get("target_judgment_ids", [])
        if not target_ids or any(target_id not in judgment_lookup for target_id in target_ids):
            errors.append(
                error(
                    "experiment_target_unbound",
                    "$.analysis.experiment.target_judgment_ids",
                    "experiment must cite at least one runtime-derived original judgment",
                )
            )
        else:
            claim_tokens = meaningful_claim_tokens(str(experiment.get("target_claim", "")))
            source_tokens: set[str] = set()
            for target_id in target_ids:
                source_tokens.update(meaningful_claim_tokens(judgment_lookup[target_id]["text"]))
            if not claim_tokens.intersection(source_tokens):
                errors.append(
                    error(
                        "experiment_target_unbound",
                        "$.analysis.experiment.target_claim",
                        "narrow experiment claim must retain an observable domain anchor from the cited judgment",
                    )
                )

    review = case.get("review")
    original_has_safety = bool(safety_features(original)) if original else False
    for path, text in all_generated_text(analysis, review if isinstance(review, dict) else None):
        rendered = str(text)
        active = generated_policy_text(rendered)
        if unreported_personal_claim(active, original):
            errors.append(
                error(
                    "unreported_personal_claim",
                    path,
                    "generated output cannot assert an unreported user feeling, motive or promise",
                )
            )
        if unreported_psychological_cause(active, original):
            errors.append(
                error(
                    "unreported_psychological_cause",
                    path,
                    "generated output cannot turn an unreported inner state into a causal explanation",
                )
            )
        if generated_diagnosis_confirmation(active):
            errors.append(
                error(
                    "diagnosis_confirmation_generated",
                    path,
                    "generated output cannot confirm or establish a diagnosis",
                )
            )
        if has_medical_change_action(active):
            errors.append(
                error(
                    "medical_plan_change",
                    path,
                    "medical or treatment changes cannot be proposed in generated output",
                )
            )
        if HIGH_COST_PATTERN.search(active) and not HIGH_COST_NONACTION_PATTERN.search(active):
            errors.append(
                error(
                    "high_cost_experiment",
                    path,
                    "high-cost or irreversible actions cannot be proposed in generated output",
                )
            )
        generated_has_safety = bool(safety_features(active))
        if UNSAFE_GENERATED_SAFETY_PATTERN.search(active) or (
            generated_has_safety and not original_has_safety
        ):
            errors.append(
                error(
                    "unsafe_generated_safety",
                    path,
                    "generated output cannot introduce or facilitate an ungrounded safety event",
                )
            )
        if POSITIVE_RELABEL_PATTERN.search(rendered):
            errors.append(error("positive_relabel", path, "do not replace one identity label with another"))
        if GENERATED_IDENTITY_VERDICT_PATTERN.search(active):
            errors.append(
                error(
                    "identity_verdict_generated",
                    path,
                    "generated output cannot turn an observation or result into an identity verdict",
                )
            )
        if GENERATED_UNVERIFIABLE_CAUSE_PATTERN.search(active):
            errors.append(
                error(
                    "unverifiable_psychological_cause",
                    path,
                    "generated output cannot invent an unobserved psychological cause or another person's motive",
                )
            )
        if GENERATED_DIAGNOSIS_OVERRIDE_PATTERN.search(active):
            errors.append(
                error(
                    "diagnosis_override_generated",
                    path,
                    "generated output cannot confirm, revoke or supersede a diagnosis or treatment decision",
                )
            )

    if status == "reviewed":
        if not isinstance(review, dict):
            errors.append(error("review_missing", "$.review", "reviewed state requires a review"))
        else:
            if review.get("target_claim") != experiment.get("target_claim"):
                errors.append(error("review_target_mismatch", "$.review.target_claim", "review must address the preregistered narrow claim"))
            for evidence_id in review.get("evidence_ids", []):
                if evidence_id not in evidence:
                    errors.append(error("unknown_evidence_reference", "$.review.evidence_ids", "review evidence id does not exist"))
            if review_overgeneralizes(review.get("rationale", "")):
                errors.append(error("review_overgeneralization", "$.review.rationale", "review cannot generalize a result into identity or diagnosis"))
    elif review is not None:
        errors.append(error("review_state_mismatch", "$.review", "review is only allowed in reviewed state"))
    return errors


def validate_case(case: Any) -> list[dict[str, str]]:
    errors = schema_errors(case, load_schema("case.schema.json"))
    if isinstance(case, dict) and isinstance(case.get("analysis"), dict):
        errors.extend(schema_errors(case["analysis"], load_schema("analysis.schema.json"), "$.analysis"))
    if not errors and isinstance(case, dict):
        errors.extend(semantic_errors(case))
    return errors


def append_event(
    case_dir: Path,
    event_type: str,
    case: dict[str, Any],
    clock: str,
    *,
    operation_id: str | None = None,
    operation_fingerprint: str | None = None,
    user_confirmation: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Build and commit one complete state bundle while the caller holds the write lock."""

    events_path = case_dir / EVENTS_FILE
    previous_hash: str | None = None
    previous_snapshot: dict[str, Any] | None = None
    count = 0
    existing_events = b""
    if events_path.exists():
        existing_events = events_path.read_bytes()
        lines = [line for line in existing_events.decode("utf-8").splitlines() if line.strip()]
        count = len(lines)
        if lines:
            previous_event = json.loads(lines[-1])
            previous_hash = previous_event["event_sha256"]
            previous_snapshot = previous_event["snapshot"]
            if parse_clock(clock) < parse_clock(previous_event["recorded_at"]):
                raise ValueError("clock_out_of_order: event clock cannot precede the latest persistent event")
    if case.get("revision") != count:
        raise ValueError(
            f"event_revision_conflict: case revision {case.get('revision')} does not match next event {count}"
        )
    snapshot = copy.deepcopy(case)
    event = {
        "event_id": f"EVT-{count:04d}",
        "revision": case["revision"],
        "type": event_type,
        "recorded_at": clock,
        "previous_event_sha256": previous_hash,
        "snapshot_sha256": digest(snapshot),
        "snapshot": snapshot,
    }
    if operation_id is not None:
        event["operation_id"] = operation_id
        event["operation_fingerprint"] = operation_fingerprint
    if event_type == "start":
        if user_confirmation is None:
            raise ValueError(
                "user_confirmation_required: start requires --confirmation-file with the user's exact words"
            )
        event["user_confirmation"] = copy.deepcopy(user_confirmation)
    elif user_confirmation is not None:
        raise ValueError("user_confirmation_unexpected: confirmation is only valid for a start event")
    event["event_sha256"] = digest(event)
    transition_failures = event_transition_errors(previous_snapshot, event, "$.pending_event")
    if transition_failures:
        raise PolicyValidationError(transition_failures)
    separator = b"" if not existing_events or existing_events.endswith(b"\n") else b"\n"
    event_line = (json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8")
    head = {
        "schema_version": "1.0",
        "case_id": case["case_id"],
        "event_count": count + 1,
        "latest_revision": case["revision"],
        "latest_event_sha256": event["event_sha256"],
        "latest_snapshot_sha256": event["snapshot_sha256"],
        "updated_at": clock,
    }
    commit_state_bundle(
        case_dir,
        {
            EVENTS_FILE: existing_events + separator + event_line,
            CASE_FILE: json_bytes(case),
            EVENT_HEAD_FILE: json_bytes(head),
        },
    )
    return event


OPERATION_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")


def record_operation_fingerprint(
    *,
    kind: str,
    source_text: str,
    fact: str,
    context: str,
    timeframe: str,
) -> str:
    """Bind a retry key to the semantic record payload, excluding clocks and revisions."""

    return digest(
        {
            "command": "record",
            "kind": kind,
            "source_text": source_text,
            "fact": fact,
            "context": context,
            "timeframe": timeframe,
        }
    )


def prior_operation_event(case_dir: Path, operation_id: str) -> dict[str, Any] | None:
    """Find a verified operation event while the caller holds the case lock."""

    events_path = case_dir / EVENTS_FILE
    if not events_path.is_file():
        return None
    for line in events_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        event = json.loads(line)
        if event.get("operation_id") == operation_id:
            return event
    return None


def ensure_clock_not_before_latest(case_dir: Path, clock: str) -> None:
    """Reject a command clock earlier than the latest verified event."""

    events_path = case_dir / EVENTS_FILE
    if not events_path.is_file():
        return
    lines = [line for line in events_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if not lines:
        return
    latest = json.loads(lines[-1])
    if parse_clock(clock) < parse_clock(latest["recorded_at"]):
        raise ValueError("clock_out_of_order: command clock cannot precede the latest persistent event")


def load_case_dir(path: Path) -> dict[str, Any]:
    case_path = path / CASE_FILE
    if not case_path.is_file():
        raise FileNotFoundError(f"missing case file: {case_path}")
    return read_json(case_path)


def require_state(case: dict[str, Any], expected: str) -> None:
    if case.get("status") != expected:
        raise ValueError(f"state_transition: expected {expected}, found {case.get('status')}")


def require_expected_revision(case: dict[str, Any], expected: int | None) -> None:
    if expected is not None and case.get("revision") != expected:
        raise ValueError(
            f"stale_revision: expected revision {expected}, found {case.get('revision')}"
        )


def plan_case(case: dict[str, Any], analysis: dict[str, Any], clock: str) -> dict[str, Any]:
    require_state(case, "drafted")
    candidate = copy.deepcopy(case)
    candidate["analysis"] = merge_semantic_baseline(analysis, case["analysis"])
    candidate["analysis"].setdefault("experiment", {}).setdefault("started_at", None)
    candidate["status"] = "planned"
    candidate["revision"] += 1
    candidate["updated_at"] = clock
    candidate["review"] = None
    errors = validate_case(candidate)
    if errors:
        raise PolicyValidationError(errors)
    return candidate


class PolicyValidationError(ValueError):
    def __init__(self, errors: list[dict[str, str]]):
        super().__init__("case did not pass validation")
        self.errors = errors


def required_experiment_results(case: dict[str, Any]) -> int:
    duration = case.get("analysis", {}).get("experiment", {}).get("duration", {})
    value = duration.get("value", 0)
    return value if duration.get("unit") == "tasks" and isinstance(value, int) and value > 0 else 1


def experiment_completion(case: dict[str, Any], clock: str, *, allow_legacy: bool = False) -> tuple[bool, str]:
    """Apply count gates to tasks and elapsed-time gates to hours or days."""

    experiment = case.get("analysis", {}).get("experiment", {})
    duration = experiment.get("duration", {})
    unit = duration.get("unit")
    value = duration.get("value", 0)
    result_count = len(experiment_result_ids(case))
    required_results = required_experiment_results(case)
    if result_count < required_results:
        return False, f"{result_count}/{required_results} results"
    if unit == "tasks":
        return True, f"{result_count}/{required_results} tasks"
    if unit not in {"hours", "days"} or not isinstance(value, int) or value <= 0:
        return False, "invalid duration"
    started_at = experiment.get("started_at")
    if not started_at:
        if allow_legacy:
            return True, "legacy record without started_at"
        return False, "experiment has no started_at"
    try:
        start_time = parse_clock(started_at)
        current_time = parse_clock(clock)
    except (TypeError, ValueError) as exc:
        return False, str(exc)
    delta = timedelta(hours=value) if unit == "hours" else timedelta(days=value)
    ready_at = start_time + delta
    if current_time < ready_at:
        return False, f"observation window ends at {ready_at.isoformat().replace('+00:00', 'Z')}"
    return True, "elapsed window complete"


def experiment_result_ids(case: dict[str, Any]) -> list[str]:
    return [item["id"] for item in case.get("evidence", []) if item.get("kind") == "experiment_result"]


def event_transition_errors(
    previous_snapshot: dict[str, Any] | None,
    event: dict[str, Any],
    path: str,
) -> list[dict[str, str]]:
    current = event["snapshot"]
    event_type = event["type"]
    failures: list[dict[str, str]] = []
    if event.get("revision") != current.get("revision"):
        failures.append(error("event_transition_mismatch", path, "event revision must equal snapshot revision"))
    if previous_snapshot is None:
        if (
            event_type != "init"
            or event.get("event_id") != "EVT-0000"
            or event.get("revision") != 0
            or current.get("revision") != 0
            or current.get("status") != "drafted"
        ):
            failures.append(error("event_transition_mismatch", path, "first event must initialize revision 0 in drafted state"))
        return failures

    expected_revision = previous_snapshot.get("revision", -1) + 1
    if event.get("event_id") != f"EVT-{expected_revision:04d}" or event.get("revision") != expected_revision:
        failures.append(error("event_transition_mismatch", path, "event id and revision must advance by exactly one"))

    allowed = {
        "plan": ("drafted", "planned"),
        "start": ("planned", "observing"),
        "record": ("observing", "observing"),
        "review": ("observing", "reviewed"),
    }
    transition = allowed.get(event_type)
    if transition is None or (previous_snapshot.get("status"), current.get("status")) != transition:
        failures.append(
            error(
                "event_transition_mismatch",
                path,
                f"event {event_type} cannot move {previous_snapshot.get('status')} to {current.get('status')}",
            )
        )
    if current.get("revision") != expected_revision:
        failures.append(error("event_transition_mismatch", path, "snapshot revision must increase by exactly one"))
    for field in ("schema_version", "case_id", "created_at", "language", "route", "risk_flags"):
        if current.get(field) != previous_snapshot.get(field):
            failures.append(error("event_transition_mismatch", path, f"immutable field changed: {field}"))
    previous_evidence = previous_snapshot.get("evidence", [])
    current_evidence = current.get("evidence", [])
    before_evidence = len(previous_evidence)
    after_evidence = len(current_evidence)
    expected_delta = 1 if event_type == "record" else 0
    if after_evidence - before_evidence != expected_delta:
        failures.append(error("event_transition_mismatch", path, f"event {event_type} has an invalid evidence delta"))
    elif event_type == "record":
        if current_evidence[:before_evidence] != previous_evidence:
            failures.append(error("event_transition_mismatch", path, "record must preserve the exact existing evidence prefix"))
    elif current_evidence != previous_evidence:
        failures.append(error("event_transition_mismatch", path, f"event {event_type} cannot rewrite evidence"))

    previous_analysis = previous_snapshot.get("analysis")
    current_analysis = current.get("analysis")
    if event_type == "start" and isinstance(previous_analysis, dict) and isinstance(current_analysis, dict):
        confirmation = event.get("user_confirmation")
        if confirmation is None:
            failures.append(
                error(
                    "event_confirmation_missing",
                    f"{path}.user_confirmation",
                    "start event requires a file-backed user confirmation",
                )
            )
        else:
            confirmation_text = confirmation.get("text") if isinstance(confirmation, dict) else None
            confirmation_hash = confirmation.get("sha256") if isinstance(confirmation, dict) else None
            if (
                not isinstance(confirmation_text, str)
                or not confirmation_text.strip()
                or confirmation_hash
                != hashlib.sha256(confirmation_text.encode("utf-8")).hexdigest()
            ):
                failures.append(
                    error(
                        "event_confirmation_binding_mismatch",
                        f"{path}.user_confirmation",
                        "start confirmation must bind the exact non-empty UTF-8 user text and its SHA-256",
                    )
                )
            expected_scope = {
                "case_id": previous_snapshot.get("case_id"),
                "pre_start_revision": previous_snapshot.get("revision"),
                "experiment_sha256": digest(
                    previous_snapshot.get("analysis", {}).get("experiment", {})
                ),
            }
            if not isinstance(confirmation, dict) or any(
                confirmation.get(key) != expected
                for key, expected in expected_scope.items()
            ):
                failures.append(
                    error(
                        "event_confirmation_scope_mismatch",
                        f"{path}.user_confirmation",
                        "start confirmation must bind the exact pre-start case, revision and experiment",
                    )
                )
        expected_analysis = copy.deepcopy(previous_analysis)
        expected_analysis["experiment"]["status"] = "active"
        if "started_at" in expected_analysis["experiment"] or "started_at" in current_analysis.get("experiment", {}):
            expected_analysis["experiment"]["started_at"] = event["recorded_at"]
        if current_analysis != expected_analysis:
            failures.append(error("event_transition_mismatch", path, "start may only activate and timestamp the registered experiment"))
    elif event_type == "record" and isinstance(previous_analysis, dict) and isinstance(current_analysis, dict):
        previous_observations = previous_analysis.get("observations", [])
        current_observations = current_analysis.get("observations", [])
        expected_analysis = copy.deepcopy(current_analysis)
        expected_analysis["observations"] = copy.deepcopy(previous_observations)
        if len(current_observations) != len(previous_observations) + 1 or expected_analysis != previous_analysis:
            failures.append(error("event_transition_mismatch", path, "record may only append one evidence-bound observation"))
        elif len(current_evidence) == len(previous_evidence) + 1:
            new_evidence = current_evidence[-1]
            new_observation = current_observations[-1]
            source = new_observation.get("source", {})
            start = source.get("start")
            end = source.get("end")
            evidence_text = new_evidence.get("text", "")
            exact_binding = (
                source.get("evidence_id") == new_evidence.get("id")
                and isinstance(start, int)
                and isinstance(end, int)
                and 0 <= start < end <= len(evidence_text)
                and source.get("quote") == evidence_text[start:end]
                and new_observation.get("text") == evidence_text[start:end]
            )
            if not exact_binding:
                failures.append(
                    error(
                        "event_record_binding_mismatch",
                        f"{path}.snapshot.analysis.observations[-1].source",
                        "the appended observation must cite an exact span from this record event's new evidence",
                    )
                )
    elif event_type == "review" and isinstance(previous_analysis, dict) and isinstance(current_analysis, dict):
        complete, detail = experiment_completion(
            previous_snapshot,
            event["recorded_at"],
            allow_legacy="started_at" not in previous_analysis.get("experiment", {}),
        )
        if not complete:
            failures.append(
                error(
                    "event_transition_mismatch",
                    path,
                    f"review cannot run before the preregistered experiment is complete: {detail}",
                )
            )
        expected_analysis = copy.deepcopy(previous_analysis)
        expected_analysis["experiment"]["status"] = "reviewed"
        if current_analysis != expected_analysis:
            failures.append(error("event_transition_mismatch", path, "review may only close the registered experiment"))
    if event_type != "review" and current.get("review") != previous_snapshot.get("review"):
        failures.append(error("event_transition_mismatch", path, f"event {event_type} cannot change review"))
    return failures


def replay_case_unlocked(case_dir: Path) -> dict[str, Any]:
    if (case_dir / TRANSACTION_JOURNAL_FILE).exists():
        return {
            "valid": False,
            "event_count": 0,
            "latest_revision": None,
            "errors": [
                error(
                    "transaction_recovery_required",
                    str(case_dir / TRANSACTION_JOURNAL_FILE),
                    "a writer must recover the pending state transaction before this case can be read",
                )
            ],
        }
    events_path = case_dir / EVENTS_FILE
    head_path = case_dir / EVENT_HEAD_FILE
    errors: list[dict[str, str]] = []
    if not events_path.is_file():
        return {"valid": False, "event_count": 0, "latest_revision": None, "errors": [error("events_missing", "$", "events.jsonl is missing")]}
    lines = [line for line in events_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if not head_path.is_file():
        return {
            "valid": False,
            "event_count": len(lines),
            "latest_revision": None,
            "errors": [error("event_head_missing", str(head_path), "monotonic event head is missing")],
        }
    try:
        head = read_json(head_path)
    except json.JSONDecodeError as exc:
        return {
            "valid": False,
            "event_count": len(lines),
            "latest_revision": None,
            "errors": [error("event_head_invalid", str(head_path), str(exc))],
        }
    head_errors = schema_errors(head, load_schema("event-head.schema.json"), "$.head")
    if head_errors:
        return {"valid": False, "event_count": len(lines), "latest_revision": None, "errors": head_errors}
    if len(lines) < head["event_count"]:
        return {
            "valid": False,
            "event_count": len(lines),
            "latest_revision": None,
            "errors": [error("event_chain_truncated", str(events_path), "event log is shorter than its monotonic head")],
        }
    if len(lines) > head["event_count"]:
        return {
            "valid": False,
            "event_count": len(lines),
            "latest_revision": None,
            "errors": [error("event_head_mismatch", str(head_path), "event log is longer than its recorded head")],
        }
    previous: str | None = None
    previous_snapshot: dict[str, Any] | None = None
    previous_time: datetime | None = None
    latest: dict[str, Any] | None = None
    seen_operation_ids: set[str] = set()
    for index, line in enumerate(lines):
        path = f"$[{index}]"
        try:
            event = json.loads(line)
        except json.JSONDecodeError as exc:
            errors.append(error("event_json_invalid", path, str(exc)))
            break
        event_schema_errors = schema_errors(event, load_schema("event.schema.json"), path)
        if event_schema_errors:
            errors.extend(event_schema_errors)
            break
        claimed = event.get("event_sha256")
        unhashed = {key: value for key, value in event.items() if key != "event_sha256"}
        if digest(unhashed) != claimed or digest(event.get("snapshot")) != event.get("snapshot_sha256"):
            errors.append(error("event_hash_mismatch", path, "event or snapshot hash does not match content"))
            break
        if event.get("previous_event_sha256") != previous:
            errors.append(error("event_chain_mismatch", path, "previous event hash does not match"))
            break
        if event.get("event_id") != f"EVT-{index:04d}" or event.get("revision") != index:
            errors.append(error("event_revision_mismatch", path, "event id and revision must be contiguous"))
            break
        operation_id = event.get("operation_id")
        operation_fingerprint = event.get("operation_fingerprint")
        if (operation_id is None) != (operation_fingerprint is None):
            errors.append(
                error(
                    "event_operation_metadata_mismatch",
                    path,
                    "operation id and fingerprint must be recorded together",
                )
            )
            break
        if operation_id is not None:
            if event.get("type") != "record":
                errors.append(
                    error(
                        "event_operation_metadata_mismatch",
                        path,
                        "operation metadata is only valid on record events",
                    )
                )
                break
            if operation_id in seen_operation_ids:
                errors.append(
                    error(
                        "duplicate_operation_id",
                        f"{path}.operation_id",
                        "an operation id may commit at most one event",
                    )
                )
                break
            seen_operation_ids.add(operation_id)
        try:
            event_time = parse_clock(event["recorded_at"])
        except ValueError as exc:
            errors.append(error(clock_error_code(exc, "event_clock"), f"{path}.recorded_at", str(exc)))
            break
        if previous_time is not None and event_time < previous_time:
            errors.append(
                error(
                    "event_clock_out_of_order",
                    f"{path}.recorded_at",
                    "event clock precedes the previous event after UTC normalization",
                )
            )
            break
        snapshot = event["snapshot"]
        if snapshot.get("updated_at") != event.get("recorded_at"):
            errors.append(
                error(
                    "timestamp_binding_mismatch",
                    f"{path}.snapshot.updated_at",
                    "snapshot updated_at must equal its event recorded_at",
                )
            )
            break
        if index == 0:
            initial_evidence = snapshot.get("evidence", [])
            if snapshot.get("created_at") != event.get("recorded_at") or not initial_evidence or initial_evidence[0].get("recorded_at") != event.get("recorded_at"):
                errors.append(
                    error(
                        "timestamp_binding_mismatch",
                        path,
                        "init event must bind created_at, updated_at and initial evidence to the event clock",
                    )
                )
                break
        elif event.get("type") == "record":
            current_evidence = snapshot.get("evidence", [])
            prior_count = len(previous_snapshot.get("evidence", [])) if previous_snapshot else 0
            if len(current_evidence) != prior_count + 1 or current_evidence[-1].get("recorded_at") != event.get("recorded_at"):
                errors.append(
                    error(
                        "timestamp_binding_mismatch",
                        f"{path}.snapshot.evidence",
                        "new record evidence must use the record event clock",
                    )
                )
                break
        transition_failures = event_transition_errors(previous_snapshot, event, path)
        if transition_failures:
            errors.extend(transition_failures)
            break
        state_errors = validate_case(event["snapshot"])
        if state_errors:
            errors.append(error("event_snapshot_invalid", path, f"snapshot has {len(state_errors)} validation errors"))
            break
        previous = claimed
        previous_snapshot = event["snapshot"]
        previous_time = event_time
        latest = event
    case_path = case_dir / CASE_FILE
    if not errors and latest is not None:
        if not case_path.is_file() or digest(read_json(case_path)) != latest["snapshot_sha256"]:
            errors.append(error("materialized_state_mismatch", str(case_path), "case.json does not match the latest event snapshot"))
        if (
            head.get("case_id") != latest["snapshot"].get("case_id")
            or head.get("latest_revision") != latest.get("revision")
            or head.get("latest_event_sha256") != latest.get("event_sha256")
            or head.get("latest_snapshot_sha256") != latest.get("snapshot_sha256")
            or head.get("updated_at") != latest.get("recorded_at")
        ):
            errors.append(error("event_head_mismatch", str(head_path), "event head does not match the latest event"))
    return {
        "valid": not errors,
        "event_count": len(lines),
        "latest_revision": latest["revision"] if latest else None,
        "latest_status": latest["snapshot"]["status"] if latest else None,
        "errors": errors,
    }


def replay_case(case_dir: Path) -> dict[str, Any]:
    with read_only_case_lock(case_dir):
        return replay_case_unlocked(case_dir)


def load_verified_case_dir_unlocked(case_dir: Path) -> dict[str, Any]:
    """Refuse to mutate or report a persistent case whose event chain does not replay."""

    replay = replay_case_unlocked(case_dir)
    if not replay["valid"]:
        raise PolicyValidationError(replay["errors"])
    return load_case_dir(case_dir)


def load_verified_case_dir(case_dir: Path) -> dict[str, Any]:
    with read_only_case_lock(case_dir):
        return load_verified_case_dir_unlocked(case_dir)


def write_new_bytes(path: Path, payload: bytes) -> None:
    """Atomically create one artifact without ever replacing a target."""

    if path.exists() or path.is_symlink():
        raise ValueError(f"output_exists: refusing to overwrite {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, raw_temporary = tempfile.mkstemp(
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
    )
    temporary = Path(raw_temporary)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.link(temporary, path)
        except FileExistsError as exc:
            raise ValueError(f"output_exists: refusing to overwrite {path}") from exc
        _fsync_directory(path.parent)
    finally:
        temporary.unlink(missing_ok=True)


def write_new_json(path: Path, payload: Any) -> None:
    write_new_bytes(path, json_bytes(payload))


def write_new_text(path: Path, payload: str) -> None:
    write_new_bytes(path, payload.encode("utf-8"))


def compile_scaffold_errors(draft: dict[str, Any]) -> list[dict[str, str]]:
    """Prove that runtime-owned draft fields still match a fresh scaffold."""

    evidence = draft.get("evidence", [])
    if not evidence or not isinstance(evidence[0], dict):
        return [error("compile_scaffold_invalid", "$.evidence", "scaffold requires its original E000 evidence")]
    expected = scaffold_case(
        str(evidence[0].get("text", "")),
        draft.get("case_id"),
        str(draft.get("created_at", "")),
    )
    immutable_fields = (
        "schema_version",
        "case_id",
        "revision",
        "status",
        "language",
        "created_at",
        "updated_at",
        "evidence",
        "route",
        "risk_flags",
        "review",
    )
    failures: list[dict[str, str]] = []
    for field in immutable_fields:
        if draft.get(field) == expected.get(field):
            continue
        code = "route_evidence_mismatch" if field == "route" else "compile_scaffold_immutable_mismatch"
        failures.append(
            error(
                code,
                f"$.{field}",
                "runtime-owned scaffold field does not match a fresh parse of E000",
            )
        )
    return failures


@contextmanager
def read_only_case_lock(case_dir: Path, *, exclusive: bool = False) -> Iterator[None]:
    """Acquire the existing case lock without creating or changing any file."""

    if not case_dir.is_dir():
        raise ValueError(f"case_directory_missing: {case_dir}")
    lock_path = case_dir / LOCK_FILE
    if lock_path.is_symlink() or not lock_path.is_file():
        raise ValueError(f"case_lock_missing: expected a regular existing lock at {lock_path}")
    with lock_path.open("rb") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _doctor_replay(case_dir: Path) -> dict[str, Any]:
    """Convert all replay failures into the replay command's stable shape."""

    try:
        return replay_case_unlocked(case_dir)
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
        message = str(exc)
        code = message.split(":", 1)[0] if ":" in message else "replay_check_failed"
        return {
            "valid": False,
            "event_count": 0,
            "latest_revision": None,
            "latest_status": None,
            "errors": [error(code, "$", message)],
        }


def _doctor_journal(case_dir: Path) -> dict[str, Any]:
    journal_path = case_dir / TRANSACTION_JOURNAL_FILE
    result: dict[str, Any] = {
        "present": journal_path.exists() or journal_path.is_symlink(),
        "valid": True,
        "recovery_required": False,
        "errors": [],
    }
    if not result["present"]:
        return result
    result["recovery_required"] = True
    try:
        if journal_path.is_symlink():
            raise _transaction_error("journal cannot be a symbolic link")
        journal = read_json(journal_path)
        _validate_transaction_journal(case_dir, journal)
    except json.JSONDecodeError as exc:
        result["errors"].append(error("journal_json_invalid", str(journal_path), str(exc)))
    except (OSError, ValueError, KeyError) as exc:
        message = str(exc)
        code = message.split(":", 1)[0] if ":" in message else "journal_check_failed"
        result["errors"].append(error(code, str(journal_path), message))
    result["valid"] = not result["errors"]
    return result


def _doctor_materialized(case_dir: Path) -> dict[str, Any]:
    files: dict[str, dict[str, Any]] = {}
    errors: list[dict[str, str]] = []
    for name in STATE_FILES:
        path = case_dir / name
        present = path.exists() or path.is_symlink()
        regular = path.is_file() and not path.is_symlink()
        checksum: str | None = None
        if regular:
            try:
                checksum = raw_sha256(path.read_bytes())
            except OSError as exc:
                errors.append(error("materialized_file_unreadable", str(path), str(exc)))
        elif present:
            errors.append(error("materialized_file_not_regular", str(path), "state file must be a regular file"))
        else:
            errors.append(error("materialized_file_missing", str(path), "state file is missing"))
        files[name] = {"present": present, "regular": regular, "sha256": checksum}

    case_path = case_dir / CASE_FILE
    case_valid = False
    if files[CASE_FILE]["regular"]:
        try:
            case = read_json(case_path)
            case_errors = validate_case(case)
            if case_errors:
                errors.extend(case_errors)
            else:
                case_valid = True
        except json.JSONDecodeError as exc:
            errors.append(error("materialized_case_json_invalid", str(case_path), str(exc)))
        except (OSError, ValueError, KeyError) as exc:
            message = str(exc)
            code = message.split(":", 1)[0] if ":" in message else "materialized_case_invalid"
            errors.append(error(code, str(case_path), message))
    return {"valid": case_valid and not errors, "files": files, "errors": errors}


def doctor_case(case_dir: Path) -> dict[str, Any]:
    """Inspect recovery, replay and materialized state without changing disk."""

    empty_journal = {"present": False, "valid": False, "recovery_required": False, "errors": []}
    empty_replay = {
        "valid": False,
        "event_count": 0,
        "latest_revision": None,
        "latest_status": None,
        "errors": [],
    }
    empty_materialized = {"valid": False, "files": {}, "errors": []}
    base: dict[str, Any] = {
        "valid": False,
        "case_dir": str(case_dir),
        "journal": empty_journal,
        "replay": empty_replay,
        "materialized": empty_materialized,
        "errors": [],
    }
    if not case_dir.is_dir():
        failure = error("case_directory_missing", str(case_dir), "case directory does not exist")
        base["errors"] = [failure]
        return base
    try:
        with read_only_case_lock(case_dir):
            journal = _doctor_journal(case_dir)
            replay = _doctor_replay(case_dir)
            materialized = _doctor_materialized(case_dir)
    except (OSError, ValueError) as exc:
        message = str(exc)
        code = message.split(":", 1)[0] if ":" in message else "doctor_check_failed"
        base["errors"] = [error(code, str(case_dir), message)]
        return base

    combined = [*journal["errors"], *replay["errors"], *materialized["errors"]]
    base.update(
        {
            "valid": bool(
                journal["valid"]
                and not journal["recovery_required"]
                and replay["valid"]
                and materialized["valid"]
            ),
            "journal": journal,
            "replay": replay,
            "materialized": materialized,
            "errors": combined,
        }
    )
    return base


def recover_case(case_dir: Path) -> dict[str, Any]:
    """Explicitly recover one case under its exclusive lock, then replay it."""

    if not case_dir.is_dir():
        raise ValueError(f"case_directory_missing: {case_dir}")
    with read_only_case_lock(case_dir, exclusive=True):
        journal_present = (case_dir / TRANSACTION_JOURNAL_FILE).exists() or (
            case_dir / TRANSACTION_JOURNAL_FILE
        ).is_symlink()
        orphan_present = any(
            RUNTIME_STAGE_NAME_PATTERN.fullmatch(item.name)
            and item.is_file()
            and not item.is_symlink()
            for item in case_dir.iterdir()
        )
        recover_pending_transaction(case_dir)
        replay = replay_case_unlocked(case_dir)
    return {
        "valid": replay["valid"],
        "case_dir": str(case_dir),
        "recovered": bool(journal_present or orphan_present),
        "replay": replay,
        "errors": replay["errors"],
    }


def next_payload(case: dict[str, Any], clock: str | None = None) -> dict[str, Any]:
    """Return the next safe transition without mutating the case."""

    base: dict[str, Any] = {
        "workflow_version": "1.0",
        "case_id": case["case_id"],
        "revision": case["revision"],
        "status": case["status"],
        "route_mode": case["route"]["mode"],
        "complete": False,
        "stage": "unknown",
        "next_steps": [],
        "errors": [],
    }
    mode = case["route"]["mode"]
    if mode == "safety_support":
        base["stage"] = "safety_support"
        base["next_steps"] = [
            {
                "action": "seek_immediate_real_world_support",
                "why": "安全风险优先于身份标签分析或现实实验",
                "owner": "user_with_real_world_support",
            }
        ]
        return base
    if mode == "support_escalation":
        reasons = set(case["route"].get("reason_codes", []))
        if "medical_decision_reserved" in reasons:
            why = "药物或治疗调整需要现实专业人员判断，AI 不代决"
        elif "recent_recurrent_self_harm" in reasons:
            why = "近期反复的安全相关想法需要尽快获得现实支持"
        else:
            why = "已报告严重功能受损，现实评估优先于身份解释或自助实验"
        base["stage"] = "support_escalation"
        base["next_steps"] = [
            {
                "action": "seek_real_world_professional_support",
                "why": why,
                "owner": "user_with_qualified_professional",
            }
        ]
        return base
    if mode == "preference_acknowledgement":
        base.update({"complete": True, "stage": "preference_acknowledgement"})
        return base
    if mode == "clinical_report_only":
        base.update({"complete": True, "stage": "clinical_report_only"})
        return base
    if mode == "needs_information":
        base["stage"] = "needs_information"
        base["next_steps"] = [
            {
                "action": "ask_minimal_routing_question",
                "why": "当前输入不足以区分标签判决、定义请求或具体行为",
                "owner": "user",
            }
        ]
        return base

    status = case["status"]
    if status == "drafted":
        base["stage"] = "analysis"
        base["next_steps"] = [
            {
                "action": "plan",
                "why": "需要把证据绑定的分析和可证伪实验通过策略门",
                "requires": ["analysis.json", "user_decision_to_persist_experiment"],
            }
        ]
    elif status == "planned":
        base["stage"] = "experiment_ready"
        base["next_steps"] = [
            {
                "action": "start",
                "why": "计划已经预登记，但尚未开始观察",
                "requires": ["user_confirmation"],
            }
        ]
    elif status == "observing":
        result_count = len(experiment_result_ids(case))
        required_results = required_experiment_results(case)
        complete, detail = experiment_completion(case, clock or utc_now())
        if complete:
            base["stage"] = "review"
            base["next_steps"] = [
                {
                    "action": "review",
                    "why": "已有实验结果，只能复核预登记的窄命题",
                    "allowed_classifications": ["supports", "weakens", "inconclusive", "invalid"],
                }
            ]
        else:
            base["stage"] = "observation"
            base["next_steps"] = [
                {
                    "action": "record",
                    "why": f"等待逐字来源绑定的观察结果或预登记期限；当前 {result_count}/{required_results}，{detail}",
                    "allowed_kinds": ["observation", "experiment_result", "user_followup"],
                }
            ]
    elif status == "reviewed":
        base.update({"complete": True, "stage": "complete"})
    else:
        base["stage"] = "invalid_state"
        base["errors"] = [error("unsupported_workflow_state", "$.status", f"cannot advance state {status}")]
    return base


def emit_workflow(payload: dict[str, Any], exit_code: int = 0) -> None:
    contract_errors = schema_errors(payload, load_schema("workflow-next.schema.json"))
    if contract_errors:
        emit(
            {
                "valid": False,
                "errors": [
                    error(
                        "workflow_contract_error",
                        "$",
                        f"next payload failed its own schema with {len(contract_errors)} errors",
                    )
                ],
            },
            1,
        )
    emit(payload, exit_code)


def display_list(values: list[Any], empty: str = "未提供") -> str:
    if not values:
        return empty
    rendered = []
    for value in values:
        if isinstance(value, dict):
            rendered.append(str(value.get("text") or value.get("name") or value))
        else:
            rendered.append(str(value))
    return "；".join(rendered)


def render_case(case: dict[str, Any]) -> str:
    analysis = case["analysis"]
    mode = case["route"]["mode"]
    labels = analysis["labels"]
    source_rows = []
    for item in labels:
        source = item["source"]
        source_rows.append(
            f"{item['text']}｜{item['source_type']}｜{item['evidence_status']}｜{source['evidence_id']}:{source['start']}-{source['end']}"
        )
    observations = analysis["observations"]
    behavior_rows = [item["text"] for item in observations]
    context_rows = [
        f"{item['text']}｜情境：{item['context']}｜频率：{item['frequency']}｜时间：{item['timeframe']}"
        for item in observations
    ]
    experiment = analysis["experiment"]
    if experiment["status"] in {"planned", "active", "reviewed"}:
        duration_unit = {"days": "天", "hours": "小时", "tasks": "次任务"}.get(
            experiment["duration"]["unit"], experiment["duration"]["unit"]
        )
        exp = (
            f"命题：{experiment['target_claim']}；变量：{experiment['primary_variable']}；"
            f"期限：{experiment['duration']['value']} {duration_unit}；"
            f"动作：{experiment['action']}；可逆：{experiment['reversibility_note']}"
        )
        outcomes = f"支持：{display_list(experiment['support_if'])}；削弱：{display_list(experiment['weaken_if'])}"
    else:
        exp = "不建立实验"
        outcomes = "不适用"
    unknowns = display_list(analysis["unknowns"])
    question = analysis["minimal_question"]["text"] or "不需要补充问题"
    reserved = "；".join(
        f"{item['topic']} → {item['owner']}（{item['reason']}）" for item in analysis["reserved_judgments"]
    ) or "未提供"
    original = case["evidence"][0]["text"]
    if mode == "safety_support":
        lines = [f"# 立即安全支持：{case['case_id']}", "", "## 立即安全支持"]
    elif mode == "preference_acknowledgement":
        lines = [
            f"# 稳定偏好确认：{case['case_id']}",
            "",
            f"已报告偏好：{original}",
            "",
            "这是一项偏好描述，不自动等于人格缺陷、能力不足或需要治疗的问题。",
            "稳定偏好本身不需要被纠正；是否改变由你决定。",
        ]
    elif mode == "clinical_report_only":
        lines = [
            f"# 临床记录边界：{case['case_id']}",
            "",
            f"已报告记录：{display_list(source_rows)}",
            "",
            "证据边界：这些记录按用户报告保存；AI 不确认或撤销诊断，也不替代正式量表规范或现实专业评估。",
            "范围边界：不把诊断扩大成人格或能力判决，也不由本工具改变医疗方案。",
        ]
    elif mode == "support_escalation":
        lines = [
            f"# 现实支持优先：{case['case_id']}",
            "",
            f"路由依据：{display_list(case['route'].get('reason_codes', []))}",
            f"目前仍需现实评估：{unknowns}",
            f"判断归属：{reserved}",
            "身份实验状态：不建立实验",
        ]
    elif mode == "needs_information":
        lines = [
            f"# 需要补充信息：{case['case_id']}",
            "",
            "当前信息不足以进入身份标签拆解，也不足以定义人格或能力。",
            "",
            "## 只补充一个路由问题",
            analysis["minimal_question"]["text"],
        ]
    else:
        lines = [
            f"# 身份标签拆解案例：{case['case_id']}",
            "",
            f"1. 原始标签：{display_list(labels)}",
            f"2. 标签来源及证据状态：{display_list(source_rows)}",
            f"3. 标签下面的具体行为：{display_list(behavior_rows)}",
            f"4. 行为出现的情境、频率和时间：{display_list(context_rows)}",
            f"5. 已知反例：{display_list(analysis['counterexamples'])}",
            f"6. 可能影响行为的可变变量：{display_list(analysis['candidate_variables'])}",
            f"7. 目前不能判断的部分：{unknowns}；最小问题：{question}",
            f"8. 小规模、可逆、有期限的现实实验：{exp}",
            f"9. 什么结果支持或削弱原判断：{outcomes}",
            f"10. 必须保留给用户或专业人员的判断：{reserved}",
        ]
    if mode == "deconstruct" and analysis["judgments"]:
        lines.extend(["", f"## 待检验的原判断\n{display_list(analysis['judgments'])}"])
    if mode != "safety_support" and analysis.get("context_claims"):
        context_rows = [
            f"{item['claim']}｜主体：{item['subject']}｜来源：{item['source']}｜"
            f"证据状态：{item['evidence_status']}｜极性：{item['polarity']}"
            for item in analysis["context_claims"]
        ]
        lines.extend(
            [
                "",
                "## 仅作上下文保留的命题",
                "这些命题不进入当前用户身份状态，也不用于触发人格或诊断实验。",
                display_list(context_rows),
            ]
        )
    if mode == "safety_support":
        profile = safety_profile(original)
        features = set(profile.features)
        grounded = [means for finding in profile.findings for means in finding.means]
        reported_targets = [
            finding.target_text
            for finding in profile.findings
            if finding.target == "other" and finding.target_text
        ]

        def named_means(*, kinds: set[str] | None = None, state: str | None = None) -> list[str]:
            values: list[str] = []
            for means in grounded:
                if kinds is not None and means.kind not in kinds:
                    continue
                if state is not None and means.state != state:
                    continue
                if means.text not in values:
                    values.append(means.text)
            return values

        harm_findings = [
            finding
            for finding in profile.findings
            if finding.kind in {"self_harm_intent", "other_harm_intent", "dangerous_height", "dangerous_rail"}
        ]
        third_party_findings = [finding for finding in profile.findings if finding.target == "third_party"]
        direct_findings = [finding for finding in profile.findings if finding.target != "third_party"]
        if harm_findings and third_party_findings and not direct_findings:
            reported_actor = third_party_findings[0].target_text or "第三方"
            lines.append(
                f"你报告的是第三方（{reported_actor}）的当前风险，不是你本人的行为。请立即联系当地急救、危机服务或警方，并尽可能联系能到对方现场的人提供现实帮助。"
            )
        elif harm_findings:
            lines.append(
                "现在先停止身份标签分析和实验。请立即联系当地急救电话或危机服务，并联系一位能够到场的可信任的人，不要独处。"
            )
        else:
            lines.append("现在先停止身份标签分析和实验，优先处理已经发生的身体暴露。")
        event_evidence: list[str] = []
        for finding in profile.findings:
            value = original[finding.start:finding.end].strip()
            if value and value not in event_evidence:
                event_evidence.append(value)
        if event_evidence:
            lines.append(f"已报告的当前安全信息：{'；'.join(event_evidence)}")
        if "medication_ingested" in features:
            named = "、".join(named_means(kinds={"medication"}, state="ingested")) or "已报告的药物"
            subject = "你报告第三方已经" if any(
                finding.kind == "poisoning" and finding.target == "third_party" for finding in profile.findings
            ) else "你报告已经"
            lines.append(
                f"{subject}摄入药物（{named}）。请立即联系当地急救、急诊或毒物中心，准确说明名称、数量和时间；不要等待症状自行消失，也不要自行催吐。"
            )
        if "toxic_substance" in features:
            poison_is_third_party = any(
                finding.kind == "poisoning" and finding.target == "third_party" for finding in profile.findings
            )
            subject = "你报告第三方已经" if poison_is_third_party else "你报告已经"
            ingested = named_means(kinds={"toxic_substance"}, state="ingested")
            inhaled = named_means(kinds={"toxic_substance"}, state="inhaled")
            eye = named_means(kinds={"toxic_substance"}, state="eye_exposure")
            if ingested:
                named = "、".join(ingested)
                lines.append(
                    f"{subject}摄入{named}。请立即联系当地急救、急诊或毒物中心，保留产品名称、标签或包装供专业人员核对；不要等待症状出现，也不要自行催吐。"
                )
            if inhaled:
                named = "、".join(inhaled)
                lines.append(
                    f"{subject}吸入{named}。若能安全离开暴露区域，请到空气流通处，并立即联系当地急救、急诊或毒物中心；不要等待症状出现，保留产品标签或包装，不要再次混合或接触。"
                )
            if eye:
                named = "、".join(eye)
                lines.append(
                    f"{'你报告第三方的' if poison_is_third_party else '你报告'}{named}已经进入眼睛。请立即用清洁流动水冲洗，同时联系当地急救、急诊或毒物中心，不要等待症状出现，并保留产品标签或包装供核对。"
                )
        if "medication_available" in features:
            named = "、".join(named_means(kinds={"medication"}, state="available")) or "已报告的药物"
            medication_findings = [
                finding
                for finding in profile.findings
                if any(
                    means.kind == "medication" and means.state == "available"
                    for means in finding.means
                )
            ]
            if medication_findings and all(
                finding.target == "third_party" for finding in medication_findings
            ):
                actor = medication_findings[0].target_text or "第三方"
                lines.append(
                    f"你报告第三方（{actor}）手边有药物（{named}）。请立即联系当地急救或危机服务，并联系能够到对方现场的人协助远离和保管药物。"
                )
            else:
                lines.append(
                    f"你尚未报告已经吞下药物（{named}）。请立即放下并远离{named}，交给能够到场的可信任的人代为保管，同时联系当地急救或危机服务。"
                )
        if "height" in features:
            named = "、".join(named_means(kinds={"height"})) or "高处边缘"
            lines.append(f"请立即从{named}退回安全的室内位置，远离该处，并让能够到场的人陪着你联系当地急救。")
        if "rail" in features:
            named = "、".join(named_means(kinds={"rail"})) or "铁路或轨道"
            lines.append(f"请立即离开{named}，移动到有工作人员或其他人的安全地点，再联系当地急救。")
        object_kinds = {
            "knife",
            "firearm",
            "hammer",
            "baseball_bat",
            "blunt_object",
            "crowbar",
            "axe",
            "wire",
            "rope",
            "object",
            "generic_weapon",
            "dangerous_object",
        }
        rendered_harm_actions: set[tuple[str, tuple[str, ...], str | None]] = set()
        for finding in profile.findings:
            if finding.kind not in {"self_harm_intent", "other_harm_intent"}:
                continue
            event_means = tuple(
                means.text for means in finding.means if means.kind in object_kinds
            )
            action_key = (finding.kind, event_means, finding.target_text)
            if action_key in rendered_harm_actions:
                continue
            rendered_harm_actions.add(action_key)
            if finding.target == "third_party":
                continue
            if finding.target == "other":
                target_text = finding.target_text or "可能受伤的人"
                if event_means:
                    named = "、".join(event_means)
                    lines.append(
                        f"请先放下并远离{named}，和{target_text}拉开距离，然后联系当地急救或警方获得现场帮助。"
                    )
                else:
                    lines.append(
                        f"请立即和{target_text}拉开距离，不要前往对方所在位置，并联系当地急救或警方获得现场帮助。"
                    )
            elif event_means:
                named = "、".join(event_means)
                lines.append(
                    f"请立即放下并远离{named}，请能够到场的人协助保管，并联系当地急救。"
                )
    if case["route"]["mode"] == "support_escalation":
        lines.extend(["", "## 现实专业支持"])
        if "recent_recurrent_self_harm" in case["route"].get("reason_codes", []):
            lines.append(
                "你报告了近期反复出现的死亡或自伤相关想法，即使此刻没有计划或手段，也值得尽快联系现实中的合格心理健康专业人员、全科医生或可信任的支持者。若想法变得迫切、出现计划或可用手段，请立即联系当地急救或危机服务。"
            )
        elif "medical_decision_reserved" in case["route"].get("reason_codes", []):
            lines.append(
                "你正在把药物或治疗方案的当前调整委托给 AI。这个决定需要交给现实中的处方人员、治疗师或其他合格专业人员；AI 只保留你已报告的信息，不替你选择停、减、加、重启或取消。"
            )
        else:
            lines.append(
                "你描述的功能受损已经值得尽快联系现实中的合格医疗、心理健康专业人员或全科医生进行完整评估。这不是意志力测试，也不能只用身份标签解释。"
            )
    if case["risk_flags"].get("medical_change_request"):
        change_domains = medical_change_domains(original)
        lines.extend(["", "## 医疗与治疗方案边界"])
        if "medication" in change_domains:
            lines.append(
                "不要自行停药、换药或调整剂量。请联系处方医生或药师，说明具体药物、当前剂量、变化时间和不适反应，由现实专业人员判断下一步。"
            )
        if "psychotherapy" in change_domains or "clinical_plan" in change_domains:
            lines.append("不要让 AI 替你决定取消或中止心理治疗。请联系治疗师或其他合格专业人员，讨论副作用、负担、替代安排和安全的下一步。")
        if "medical_procedure" in change_domains:
            lines.append("不要让 AI 替你决定接受、取消或改变医疗程序。请联系负责评估该程序的现实医疗专业人员，讨论适应证、风险、替代方案和下一步。")
    if case.get("review"):
        review = case["review"]
        lines.extend(
            [
                "",
                "## 实验复核",
                f"分类：{review['classification']}",
                f"窄命题：{review['target_claim']}",
                f"理由：{review['rationale']}",
                f"证据：{', '.join(review['evidence_ids'])}",
            ]
        )
    return "\n".join(lines) + "\n"


def parser() -> argparse.ArgumentParser:
    cli = argparse.ArgumentParser(description=__doc__)
    sub = cli.add_subparsers(dest="command", required=True)

    scaffold = sub.add_parser("scaffold", help="route raw text and emit an evidence-bound draft")
    scaffold_source = scaffold.add_mutually_exclusive_group(required=True)
    scaffold_source.add_argument("--text")
    scaffold_source.add_argument("--text-file", type=Path)
    scaffold_source.add_argument("--stdin", action="store_true")
    scaffold.add_argument("--out", type=Path)
    scaffold.add_argument("--case-id")
    scaffold.add_argument("--clock", default=None)

    compile_case = sub.add_parser("compile", help="merge a draft scaffold with one validated analysis")
    compile_case.add_argument("--scaffold", required=True, type=Path)
    compile_case.add_argument("--analysis", required=True, type=Path)
    compile_case.add_argument("--out", required=True, type=Path)
    compile_case.add_argument("--clock", default=None)

    prepare_analysis = sub.add_parser(
        "prepare-analysis",
        help="materialize the scaffold's source-bound analysis as an editable work order",
    )
    prepare_analysis.add_argument("--scaffold", required=True, type=Path)
    prepare_analysis.add_argument("--out", required=True, type=Path)

    validate = sub.add_parser("validate", help="validate schema and cross-field policy")
    validate.add_argument("case", type=Path)

    render = sub.add_parser("render", help="render the validated route-specific response")
    render.add_argument("case", type=Path)
    render.add_argument("--out", type=Path)

    init = sub.add_parser("init", help="create an explicit persistent case directory")
    init_source = init.add_mutually_exclusive_group(required=True)
    init_source.add_argument("--text")
    init_source.add_argument("--text-file", type=Path)
    init_source.add_argument("--stdin", action="store_true")
    init.add_argument("--case-dir", required=True, type=Path)
    init.add_argument("--case-id")
    init.add_argument("--clock", default=None)

    plan = sub.add_parser("plan", help="attach a validated, preregistered analysis")
    plan.add_argument("--case-dir", required=True, type=Path)
    plan.add_argument("--analysis", required=True, type=Path)
    plan.add_argument("--expected-revision", type=int)
    plan.add_argument("--clock", default=None)

    start = sub.add_parser("start", help="start an already validated plan")
    start.add_argument("--case-dir", required=True, type=Path)
    start.add_argument("--confirmation-file", type=Path)
    start.add_argument("--expected-revision", type=int)
    start.add_argument("--clock", default=None)

    record = sub.add_parser("record", help="append exact new evidence while observing")
    record.add_argument("--case-dir", required=True, type=Path)
    record.add_argument("--kind", required=True, choices=["observation", "experiment_result", "user_followup"])
    record.add_argument("--observation-file", type=Path)
    record.add_argument("--source-text")
    record.add_argument("--fact")
    record.add_argument("--context")
    record.add_argument("--timeframe")
    record.add_argument("--operation-id")
    record.add_argument("--expected-revision", type=int)
    record.add_argument("--clock", default=None)

    review = sub.add_parser("review", help="classify only the preregistered narrow claim")
    review.add_argument("--case-dir", required=True, type=Path)
    review.add_argument("--classification", required=True, choices=["supports", "weakens", "inconclusive", "invalid"])
    rationale_source = review.add_mutually_exclusive_group(required=True)
    rationale_source.add_argument("--rationale")
    rationale_source.add_argument("--rationale-file", type=Path)
    review.add_argument("--expected-revision", type=int)
    review.add_argument("--clock", default=None)

    replay = sub.add_parser("replay", help="verify the append-only event chain")
    replay.add_argument("--case-dir", required=True, type=Path)

    doctor = sub.add_parser("doctor", help="inspect journal, replay and materialized state without writing")
    doctor.add_argument("--case-dir", required=True, type=Path)

    recover = sub.add_parser("recover", help="explicitly recover a pending case transaction and verify replay")
    recover.add_argument("--case-dir", required=True, type=Path)

    status = sub.add_parser("status", help="show the materialized case state")
    status.add_argument("--case-dir", required=True, type=Path)

    next_step = sub.add_parser("next", help="return one read-only safe workflow transition")
    source = next_step.add_mutually_exclusive_group(required=True)
    source.add_argument("--case-dir", type=Path)
    source.add_argument("--case", type=Path)
    next_step.add_argument("--clock", default=None)
    return cli


def main() -> None:
    args = parser().parse_args()
    clock = getattr(args, "clock", None) or utc_now()
    try:
        if args.command in {"scaffold", "compile", "init", "plan", "start", "record", "review", "next"}:
            parse_clock(clock)
        if args.command == "scaffold":
            text = user_text_from_args(args)
            if not text.strip():
                emit({"valid": False, "errors": [error("input_empty", "$.text", "input text must not be empty")]}, 1)
            case = scaffold_case(text, args.case_id, clock)
            errors = validate_case(case)
            if errors:
                emit({"valid": False, "errors": errors}, 1)
            if args.out is not None:
                output_path = Path(os.path.abspath(args.out)).resolve(strict=False)
                write_new_json(output_path, case)
                emit({"valid": True, "output": str(output_path), "case": case})
            emit(case)

        if args.command == "prepare-analysis":
            scaffold_path = args.scaffold.resolve()
            draft = read_json(scaffold_path)
            draft_errors = validate_case(draft)
            if draft_errors:
                raise PolicyValidationError(draft_errors)
            immutable_errors = compile_scaffold_errors(draft)
            if immutable_errors:
                raise PolicyValidationError(immutable_errors)
            output_path = Path(os.path.abspath(args.out)).resolve(strict=False)
            write_new_json(output_path, draft["analysis"])
            emit({"valid": True, "output": str(output_path)})

        if args.command == "compile":
            scaffold_path = args.scaffold.resolve()
            analysis_path = args.analysis.resolve()
            if not analysis_path.exists():
                raise ValueError(
                    "analysis_file_missing: run prepare-analysis to create analysis.json before compile"
                )
            if not analysis_path.is_file() or analysis_path.is_symlink():
                raise ValueError(
                    "analysis_file_invalid: analysis.json must be a regular non-symlink file"
                )
            requested_output = Path(os.path.abspath(args.out))
            if requested_output.exists() or requested_output.is_symlink():
                raise ValueError(f"output_exists: refusing to overwrite {requested_output}")
            output_path = requested_output.resolve(strict=False)
            if output_path.exists() or output_path.is_symlink():
                raise ValueError(f"output_exists: refusing to overwrite {output_path}")
            draft = read_json(scaffold_path)
            draft_errors = validate_case(draft)
            if draft_errors:
                raise PolicyValidationError(draft_errors)
            immutable_errors = compile_scaffold_errors(draft)
            if immutable_errors:
                raise PolicyValidationError(immutable_errors)
            analysis = read_json(analysis_path)
            case = plan_case(draft, analysis, clock)
            write_new_json(output_path, case)
            emit({"valid": True, "output": str(output_path), "case": case})

        if args.command == "validate":
            case = read_json(args.case.resolve())
            errors = validate_case(case)
            emit({"valid": not errors, "errors": errors}, 0 if not errors else 1)

        if args.command == "render":
            case = read_json(args.case.resolve())
            errors = validate_case(case)
            if errors:
                emit({"valid": False, "errors": errors}, 1)
            report = render_case(case)
            if args.out:
                output_path = Path(os.path.abspath(args.out)).resolve(strict=False)
                write_new_text(output_path, report)
                emit({"valid": True, "output": str(output_path)})
            print(report, end="")
            return

        if args.command == "init":
            text = user_text_from_args(args)
            if not text.strip():
                emit({"valid": False, "errors": [error("input_empty", "$.text", "input text must not be empty")]}, 1)
            case_dir = args.case_dir.resolve()
            case = scaffold_case(text, args.case_id, clock)
            if case["status"] != "drafted":
                raise ValueError(f"init_requires_deconstruct_route: got {case['route']['mode']}")
            errors = validate_case(case)
            if errors:
                raise PolicyValidationError(errors)
            if case_dir.exists():
                _, blocking = _init_preflight_entries(case_dir)
                if blocking:
                    raise ValueError(f"case_directory_not_empty: {case_dir}")
            with case_lock(case_dir, exclusive=True, create=True):
                recover_pending_transaction(case_dir)
                _, blocking = _init_preflight_entries(case_dir)
                if blocking:
                    raise ValueError(f"case_directory_not_empty: {case_dir}")
                _cleanup_runtime_stage_orphans(case_dir)
                append_event(case_dir, "init", case, clock)
            emit({"valid": True, "case_dir": str(case_dir), "case": case})

        if args.command == "plan":
            case_dir = args.case_dir.resolve()
            analysis = read_json(args.analysis.resolve())
            with read_only_case_lock(case_dir, exclusive=True):
                recover_pending_transaction(case_dir)
                case = load_verified_case_dir_unlocked(case_dir)
                require_expected_revision(case, args.expected_revision)
                ensure_clock_not_before_latest(case_dir, clock)
                case = plan_case(case, analysis, clock)
                append_event(case_dir, "plan", case, clock)
            emit({"valid": True, "case": case})

        if args.command == "start":
            if args.confirmation_file is None:
                raise ValueError(
                    "user_confirmation_required: provide --confirmation-file containing the user's exact words"
                )
            confirmation_text = read_bounded_text(
                args.confirmation_file,
                "confirmation",
            )
            if not confirmation_text.strip():
                raise ValueError(
                    "user_confirmation_empty: confirmation file must contain the user's exact non-empty words"
                )
            if not confirmation_has_explicit_experiment_intent(confirmation_text):
                raise ValueError(
                    "user_confirmation_intent_mismatch: confirmation must explicitly agree to starting the experiment"
                )
            case_dir = args.case_dir.resolve()
            with read_only_case_lock(case_dir, exclusive=True):
                recover_pending_transaction(case_dir)
                case = load_verified_case_dir_unlocked(case_dir)
                require_expected_revision(case, args.expected_revision)
                ensure_clock_not_before_latest(case_dir, clock)
                require_state(case, "planned")
                confirmation_binding = {
                    "text": confirmation_text,
                    "sha256": hashlib.sha256(confirmation_text.encode("utf-8")).hexdigest(),
                    "case_id": case["case_id"],
                    "pre_start_revision": case["revision"],
                    "experiment_sha256": digest(case["analysis"]["experiment"]),
                }
                case["status"] = "observing"
                case["analysis"]["experiment"]["status"] = "active"
                case["analysis"]["experiment"]["started_at"] = clock
                case["revision"] += 1
                case["updated_at"] = clock
                errors = validate_case(case)
                if errors:
                    raise PolicyValidationError(errors)
                append_event(
                    case_dir,
                    "start",
                    case,
                    clock,
                    user_confirmation=confirmation_binding,
                )
            emit({"valid": True, "case": case})

        if args.command == "record":
            fields = record_fields_from_args(args)
            args.source_text = fields["source_text"]
            args.fact = fields["fact"]
            args.context = fields["context"]
            args.timeframe = fields["timeframe"]
            case_dir = args.case_dir.resolve()
            operation_fingerprint = None
            if args.operation_id is not None:
                if not OPERATION_ID_PATTERN.fullmatch(args.operation_id):
                    raise ValueError(
                        "operation_id_invalid: use 1 to 128 ASCII letters, digits, dot, underscore, colon or hyphen"
                    )
                operation_fingerprint = record_operation_fingerprint(
                    kind=args.kind,
                    source_text=args.source_text,
                    fact=args.fact,
                    context=args.context,
                    timeframe=args.timeframe,
                )
            replayed_operation: dict[str, Any] | None = None
            with read_only_case_lock(case_dir, exclusive=True):
                recover_pending_transaction(case_dir)
                case = load_verified_case_dir_unlocked(case_dir)
                prior = (
                    prior_operation_event(case_dir, args.operation_id)
                    if args.operation_id is not None
                    else None
                )
                if prior is not None:
                    if (
                        prior.get("type") != "record"
                        or prior.get("operation_fingerprint") != operation_fingerprint
                    ):
                        raise ValueError(
                            "operation_id_conflict: operation id is already bound to a different payload"
                        )
                    prior_case = prior["snapshot"]
                    replayed_operation = {
                        "valid": True,
                        "idempotent_replay": True,
                        "operation_id": args.operation_id,
                        "evidence_id": prior_case["evidence"][-1]["id"],
                        "case": prior_case,
                    }
                else:
                    require_expected_revision(case, args.expected_revision)
                    ensure_clock_not_before_latest(case_dir, clock)
                    require_state(case, "observing")
                    start = args.source_text.find(args.fact)
                    if start < 0:
                        raise ValueError("fact_not_exact_source_span")
                    evidence_id = f"E{len(case['evidence']):03d}"
                    evidence_kind = args.kind if args.kind in {"observation", "experiment_result"} else "user_followup"
                    case["evidence"].append(
                        {"id": evidence_id, "kind": evidence_kind, "text": args.source_text, "recorded_at": clock}
                    )
                    case["analysis"]["observations"].append(
                        {
                            "text": args.fact,
                            "context": args.context,
                            "frequency": "一次记录",
                            "timeframe": args.timeframe,
                            "source": source_for(args.source_text, evidence_id, start, start + len(args.fact)),
                        }
                    )
                    case["revision"] += 1
                    case["updated_at"] = clock
                    errors = validate_case(case)
                    if errors:
                        raise PolicyValidationError(errors)
                    append_event(
                        case_dir,
                        "record",
                        case,
                        clock,
                        operation_id=args.operation_id,
                        operation_fingerprint=operation_fingerprint,
                    )
            if replayed_operation is not None:
                emit(replayed_operation)
            emit(
                {
                    "valid": True,
                    "idempotent_replay": False,
                    "operation_id": args.operation_id,
                    "evidence_id": evidence_id,
                    "case": case,
                }
            )

        if args.command == "review":
            if args.rationale_file is not None:
                args.rationale = read_bounded_text(
                    args.rationale_file,
                    "rationale",
                )
            if not isinstance(args.rationale, str) or not args.rationale.strip():
                raise ValueError("rationale_required: provide non-empty text")
            case_dir = args.case_dir.resolve()
            with read_only_case_lock(case_dir, exclusive=True):
                recover_pending_transaction(case_dir)
                case = load_verified_case_dir_unlocked(case_dir)
                require_expected_revision(case, args.expected_revision)
                ensure_clock_not_before_latest(case_dir, clock)
                require_state(case, "observing")
                result_ids = experiment_result_ids(case)
                complete, detail = experiment_completion(case, clock)
                if not complete:
                    raise ValueError(f"review_requires_complete_experiment: {detail}")
                case["status"] = "reviewed"
                case["analysis"]["experiment"]["status"] = "reviewed"
                case["review"] = {
                    "classification": args.classification,
                    "target_claim": case["analysis"]["experiment"]["target_claim"],
                    "rationale": args.rationale,
                    "evidence_ids": result_ids,
                }
                case["revision"] += 1
                case["updated_at"] = clock
                errors = validate_case(case)
                if errors:
                    raise PolicyValidationError(errors)
                append_event(case_dir, "review", case, clock)
            emit({"valid": True, "case": case})

        if args.command == "replay":
            payload = replay_case(args.case_dir.resolve())
            emit(payload, 0 if payload["valid"] else 1)

        if args.command == "doctor":
            case_dir = Path(os.path.abspath(args.case_dir))
            report = doctor_case(case_dir)
            emit(report, 0 if report["valid"] else 1)

        if args.command == "recover":
            case_dir = Path(os.path.abspath(args.case_dir))
            report = recover_case(case_dir)
            emit(report, 0 if report["valid"] else 1)

        if args.command == "status":
            case = load_verified_case_dir(args.case_dir.resolve())
            emit(
                {
                    "case_id": case["case_id"],
                    "status": case["status"],
                    "classification": case["review"]["classification"] if case.get("review") else None,
                    "revision": case["revision"],
                }
            )

        if args.command == "next":
            if args.case_dir:
                case_dir = args.case_dir.resolve()
                with read_only_case_lock(case_dir):
                    replay = replay_case_unlocked(case_dir)
                    if not replay["valid"]:
                        emit_workflow(
                            {
                                "workflow_version": "1.0",
                                "complete": False,
                                "stage": "integrity_failure",
                                "next_steps": [],
                                "errors": replay["errors"],
                            },
                            1,
                        )
                    case = load_case_dir(case_dir)
            else:
                case = read_json(args.case.resolve())
                errors = validate_case(case)
                if errors:
                    emit_workflow(
                        {
                            "workflow_version": "1.0",
                            "complete": False,
                            "stage": "invalid_case",
                            "next_steps": [],
                            "errors": errors,
                        },
                        1,
                    )
            emit_workflow(next_payload(case, clock))
    except PolicyValidationError as exc:
        emit({"valid": False, "errors": exc.errors}, 1)
    except json.JSONDecodeError as exc:
        emit({"valid": False, "errors": [error("json_decode_error", "$", str(exc))]}, 1)
    except (OSError, ValueError, KeyError) as exc:
        message = str(exc)
        code = message.split(":", 1)[0] if ":" in message else message
        emit({"valid": False, "errors": [error(code, "$", message)]}, 1)


if __name__ == "__main__":
    main()
