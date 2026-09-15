# -*- coding: utf-8 -*-
import os
d = r"F:\LLMGal\frontend\src\assets\voice\_samples"
files = sorted(os.listdir(d))
bad = []
total = 0
for f in files:
    p = os.path.join(d, f)
    n = os.path.getsize(p)
    total += n
    if n < 1000:
        bad.append((f, n))
print("count =", len(files))
print("total KB = %.1f" % (total / 1024))
print("empty/too small =", bad if bad else "none")
