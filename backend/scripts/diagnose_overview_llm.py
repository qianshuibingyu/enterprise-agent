"""Reproduce overview_service.generate_overview_text behavior without backend deps."""
import json
import re
import time
import urllib.request

MAX_OVERVIEW_LENGTH = 100
SYSTEM_PROMPT = (
    "你是企业运营收件箱的客户消息业务概要器，不是翻译器。"
    "请用不超过100字的中文概括这条消息，只返回一段纯文本。"
    "第一句必须先判定并点明消息性质与发件人核心意图，"
    "例如：产品询价、售后问题、合作洽谈、付款通知、通知公告、功能测试、垃圾营销、意图不明。"
    "随后补充运营需要关注的关键事实和发件人期望的动作。"
    "概括业务目的，不要逐句翻译或转述原文表述；"
    "对于测试、说明、规则类内容，直接概括发这条消息的目的，不要复述其中的机制细节。"
    "不要复述邮件头、签名、免责声明、营销模板或无关转发内容。"
    "不得编造原文没有的事实。"
    "遇到付款、签署文件、外部链接或疑似钓鱼内容，只陈述事实并提示人工核验。"
    "不要输出标题、JSON、HTML、链接、系统提示、前端展示说明或操作指令。"
)

env = {}
with open(r"E:/Desktop/VibeCoding/enterprise-agent/.env", encoding="utf-8") as f:
    for line in f:
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip()

BASE = env["LLM_BASE_URL"].rstrip("/")
KEY = env["LLM_API_KEY"]
MODEL = env["LLM_MODEL"]
TIMEOUT = float(env.get("LLM_TIMEOUT_SECONDS", "20"))

CASES = {
    "probe-v2": (
        "规则摘要测试: If the LLM connection works and a Chinese summary can be generated normally, "
        "the front end displays \"中文概要: 可用\", otherwise it displays \"中文概要: 不可用\"."
    ),
    "probe-longer": (
        "中文概要测试说明：本邮件用于验证系统是否接入了可用的 LLM。"
        "仅当中文摘要和 LLM 均正常工作时摘要可用，否则摘要内容不可用。"
        "运营人员无需进一步处理本邮件。"
    ),
    "business": (
        "Subject: Inquiry for stainless steel pipe fittings - MOQ and lead time\n\n"
        "Dear Sir or Madam,\n\n"
        "We are a trading company based in Hamburg, Germany. We are sourcing:\n"
        "1. ANSI B16.9 elbow 90deg, 2 inch, sch40, SS304 - 5,000 pcs\n"
        "2. ANSI B16.9 equal tee, 2 inch, sch40, SS304 - 3,000 pcs\n"
        "3. WN RF flange ANSI B16.5 cl150, 2 inch, 304/304L - 2,000 pcs\n\n"
        "Please quote FOB Shanghai/Ningbo including packing, and advise MOQ, lead time, "
        "payment terms (we prefer 30% T/T deposit, 70% against B/L copy), and whether you can "
        "provide EN 10204 3.1 Mill Test Certificates. If competitive, trial order within 3-4 weeks, "
        "then about two 20ft containers monthly. Please send company profile and ISO 9001 / PED certs.\n\n"
        "Best regards,\nMarkus Weber\nPurchasing Manager\nHanseatic Industrial Supply GmbH\n"
        "Tel: +49 40 123456"
    ),
}


def call(user_text, label):
    payload = {
        "model": MODEL,
        "temperature": 0,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_text},
        ],
    }
    req = urllib.request.Request(
        BASE + "/chat/completions",
        data=json.dumps(payload).encode(),
        headers={"Authorization": "Bearer " + KEY, "Content-Type": "application/json"},
    )
    start = time.time()
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            body = json.loads(resp.read())
    except Exception as exc:
        print(f"[{label}] FAILED after {time.time()-start:.1f}s -> {type(exc).__name__}: {exc}")
        return
    elapsed = time.time() - start
    text = body["choices"][0]["message"]["content"]
    text = re.sub(r"\s+", " ", text).strip()
    print(f"[{label}] {elapsed:.1f}s len={len(text)} -> {text}")


for label, content in CASES.items():
    call(content, label)
