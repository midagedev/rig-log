#!/usr/bin/env python3
# Factual-QA probe: greedy, no thinking, short answers. usage: probe.py <port> <out.json>
import json, sys, time, urllib.request
port, out = sys.argv[1], sys.argv[2]
Q = [
 ("Who wrote the novel 'The Vegetarian' that won the 2016 Man Booker International Prize?", "Han Kang"),
 ("In what year was the Treaty of Westphalia signed?", "1648"),
 ("What is the capital of Burkina Faso?", "Ouagadougou"),
 ("Who won the Nobel Prize in Physics in 1921?", "Albert Einstein"),
 ("What is the chemical formula of caffeine?", "C8H10N4O2"),
 ("Which river flows through Baghdad?", "Tigris"),
 ("Who composed the opera 'The Cunning Little Vixen'?", "Leoš Janáček"),
 ("What is the atomic number of tungsten?", "74"),
 ("In which year did the Sewol ferry disaster occur?", "2014"),
 ("Who was the first woman to win the Fields Medal?", "Maryam Mirzakhani"),
 ("What is the tallest mountain in Africa?", "Kilimanjaro"),
 ("Which element has the symbol Rb?", "rubidium"),
 ("Who directed the 1954 film 'Seven Samurai'?", "Akira Kurosawa"),
 ("What is the SI unit of magnetic flux?", "weber"),
 ("Which Korean king created the Hangul alphabet, and in what year was it promulgated?", "Sejong; 1446"),
 ("Who wrote the 1927 paper introducing the uncertainty principle?", "Werner Heisenberg"),
 ("What is the capital of Kyrgyzstan?", "Bishkek"),
 ("Which programming language was designed by Bjarne Stroustrup?", "C++"),
 ("How many moons does Mars have, and what are their names?", "2; Phobos and Deimos"),
 ("Who painted 'The Garden of Earthly Delights'?", "Hieronymus Bosch"),
 ("What year did the Chernobyl disaster happen?", "1986"),
 ("Which enzyme unwinds DNA during replication?", "helicase"),
 ("Who is the author of 'Pachinko' (2017)?", "Min Jin Lee"),
 ("What is the boiling point of nitrogen at 1 atm in kelvin?", "77 K"),
]
res = []
for q, a in Q:
    body = {"model":"x","messages":[{"role":"system","content":"Answer with the fact only, in at most one short sentence."},{"role":"user","content":q}],
            "temperature":0,"max_tokens":48,"reasoning_effort":"none","chat_template_kwargs":{"reasoning_effort":"none"}}
    req = urllib.request.Request(f"http://127.0.0.1:{port}/v1/chat/completions", data=json.dumps(body).encode(), headers={"Content-Type":"application/json"})
    t0=time.time(); r = json.load(urllib.request.urlopen(req, timeout=600)); dt=time.time()-t0
    ans = r["choices"][0]["message"]["content"].strip()
    tim = r.get("timings",{})
    res.append({"q":q,"expect":a,"answer":ans,"secs":round(dt,1),"pred_tps":tim.get("predicted_per_second"),"prompt_n":tim.get("prompt_n"),"predicted_n":tim.get("predicted_n")})
    print(f"[{len(res):2d}] {dt:5.1f}s  {ans[:90]!r}", flush=True)
json.dump(res, open(out,"w"), indent=1, ensure_ascii=False)
