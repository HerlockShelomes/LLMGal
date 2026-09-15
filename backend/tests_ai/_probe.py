import os, sys, time
_BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _BACKEND)
import config
print("PY_OK")
print("PROVIDER=", config.TEXT_PROVIDER)
print("MODEL=", config.TEXT_MODEL)
print("BASE_URL=", config.TEXT_BASE_URL)
print("KEY_PRESENT=", bool(config.TEXT_API_KEY))
print("KEY_LEN=", len(config.TEXT_API_KEY or ""))
print("ALLOWLIST=", sorted(config.TEXT_MODEL_ALLOWLIST))

# 尝试导入真实被测模块（确认依赖可用）
try:
    import Text
    import Integration
    print("IMPORT_OK")
except Exception as e:
    print("IMPORT_FAIL", repr(e))

# 极简真实连通性探测（15s 超时），无密钥会快速失败，不计费
if config.TEXT_API_KEY:
    try:
        from openai import OpenAI
        c = OpenAI(api_key=config.TEXT_API_KEY, base_url=config.TEXT_BASE_URL, timeout=15)
        t0 = time.time()
        r = c.chat.completions.create(
            model=config.resolve_text_model(None),
            stream=False,
            max_tokens=8,
            messages=[{"role": "user", "content": "ping"}],
        )
        print("NET_OK", time.time()-t0, repr((r.choices[0].message.content if r.choices else None)[:30]))
    except Exception as e:
        print("NET_FAIL", repr(e)[:300])
else:
    print("NET_SKIP no key")
