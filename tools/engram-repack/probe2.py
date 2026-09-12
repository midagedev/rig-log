#!/usr/bin/env python3
# Factual-QA probe: greedy, no thinking, short answers. usage: probe.py <port> <out.json>
import json, sys, time, urllib.request
port, out = sys.argv[1], sys.argv[2]
Q = [
 ("Who wrote the Korean novel '난장이가 쏘아올린 작은 공'?", "조세희 (Cho Se-hui)"),
 ("Who discovered the element francium, and in what year?", "Marguerite Perey, 1939"),
 ("Which Japanese author wrote the novel 'Kokoro'?", "Natsume Sōseki"),
 ("What is the ISO 4217 currency code of Mongolia's currency?", "MNT"),
 ("Which cyclist won the 1998 Tour de France?", "Marco Pantani"),
 ("Who wrote the poem '진달래꽃'?", "김소월"),
 ("What is the melting point of gallium in degrees Celsius?", "29.76"),
 ("What was the name of the first Korean satellite, launched in 1992?", "우리별 1호 / KITSAT-1"),
 ("Who was the 14th President of the United States?", "Franklin Pierce"),
 ("What is the IATA airport code of Daegu International Airport?", "TAE"),
 ("Who wrote the multi-volume Korean novel '토지'?", "박경리"),
 ("Who was South Korea's goalkeeper at the 2002 FIFA World Cup?", "이운재 Lee Woon-jae"),
 ("In what year did King Jeongjo of Joseon die?", "1800"),
 ("What is the half-life of carbon-14 in years?", "5730"),
 ("Who composed the 'Gymnopédies'?", "Erik Satie"),
 ("In what year was 'Frankenstein' by Mary Shelley first published?", "1818"),
 ("Which Soviet space station was launched in 1986?", "Mir"),
 ("Who wrote 'The Master and Margarita'?", "Mikhail Bulgakov"),
 ("In which year was 'One Hundred Years of Solitude' first published?", "1967"),
 ("What is the capital of Tasmania?", "Hobart"),
 ("Who was the first Korean to win the Nobel Prize, and in what year?", "Kim Dae-jung, 2000"),
 ("What is the name of the strait between Korea and Japan?", "Korea Strait (Tsushima)"),
 ("Who directed the 2003 film '살인의 추억'?", "봉준호"),
 ("Which mathematician proved Fermat's Last Theorem, and in what year was the proof published?", "Andrew Wiles, 1995"),
 ("What is the atomic mass of copper to two decimals?", "63.55"),
 ("Which country has the ccTLD .kg?", "Kyrgyzstan"),
 ("Who wrote the opera 'Rusalka' (1901)?", "Antonín Dvořák"),
 ("In what year was the Seoul Metro Line 1 opened?", "1974"),
 # Q29 was unscorable (no gold answer known to the author) and is excluded from the 29 scored questions in the log.
 ("Who was the author of the Silla-era 'Samguk Sagi', and in what year was it completed?", "김부식 Kim Bu-sik, 1145"),
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
