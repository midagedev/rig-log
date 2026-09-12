import json
a=json.load(open("/tmp/popqa-Q3.json")); b=json.load(open("/tmp/popqa-Q8.json"))
def acc(rs): return sum(r["ok"] for r in rs)/len(rs)
print("band        n   Q3     Q8")
for name,sl in (("low-pop",slice(0,200)),("mid-pop",slice(200,400)),("all",slice(0,400))):
    print(f"{name:10s} {len(a[sl]):3d}  {acc(a[sl]):.3f}  {acc(b[sl]):.3f}")
flip=[(x,y) for x,y in zip(a,b) if x["ok"]!=y["ok"]]
print("flips:",len(flip),"Q3-only-right",sum(1 for x,y in flip if x["ok"]),"Q8-only-right",sum(1 for x,y in flip if y["ok"]))
diff=sum(1 for x,y in zip(a,b) if x["answer"]!=y["answer"]); print("answer text differs:",diff,"/ 400")
for x,y in flip[:12]:
    print(f"- pop={x['pop']} {x['q']!r} gold={x['answers'][:2]}\n    Q3: {x['answer'][:80]!r} ok={x['ok']}\n    Q8: {y['answer'][:80]!r} ok={y['ok']}")
