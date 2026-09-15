import os, sys, re, time
_BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _BACKEND)
os.chdir(_BACKEND)
import Text, Integration

t0 = time.time()
ans = Text.get_llm_response(None, "Wendy", {"role": "user", "content": "我今天有点累，但又完成了一个小目标，你安慰我一下并给我一个放松建议好吗？"})
print("ELAPSED", round(time.time()-t0, 2))
print("RAW_OUTPUT_START")
print(ans)
print("RAW_OUTPUT_END")
m = re.findall(r'\((.*?)\)', ans)
print("PARSED_BRACKETS", m)
if len(m) >= 2:
    print("EMOTION", m[0], "REASON", m[1])
