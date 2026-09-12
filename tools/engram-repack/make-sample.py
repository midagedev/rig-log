# Build a 400-question PopQA sample: 200 lowest-popularity + 200 around the median, fixed seed.
import json, random
from datasets import load_dataset
ds=load_dataset("akariasai/PopQA",split="test")
rows=[{"id":r["id"],"question":r["question"],"answers":json.loads(r["possible_answers"]),"pop":r["s_pop"]} for r in ds]
rows.sort(key=lambda r:r["pop"])
random.seed(13)
low=random.sample(rows[:2000],200); mid=random.sample(rows[len(rows)//2-1000:len(rows)//2+1000],200)
json.dump(low+mid,open("/tmp/popqa-sample.json","w"),ensure_ascii=False)
print(len(rows),"total; sample pops", low[0]["pop"], "…", mid[-1]["pop"])
