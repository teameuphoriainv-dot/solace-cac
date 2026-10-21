# Red-flag stress test

Generated 2026-10-19 by `scripts/red_flag_report.py`. These runs use no AI key. The trained model was on.

## What we tested

We ran 1707 check-ins through the scoring, in 20 languages, in four sets, and a fifth set is run separately:

* **Pinned phrases** (186). The phrases pinned by `backend/tests/test_red_flags.py`.
* **Red-team regression set** (994). Check-ins that two red teams of Claude Code agents wrote to break the rules: typos, teen slang, someone typing for a person who collapsed, overdoses by drug name, pregnancy, babies, all 20 languages, other languages typed in Latin letters, and everyday traps like "my infection is not responding to antibiotics". We used these to find and fix misses, and `backend/tests/test_redteam_regression.py` pins them.
* **Held-out set** (287). New check-ins written after the first fixes were frozen. We never tuned the rules to them.
* **Blind test 1 (now a diagnostic set)** (240). Written and frozen by another Claude Code agent before it looked at the rules or the tests, and run once blind. We then fixed the rules by category using its misses, so it is no longer blind. It is kept as a diagnostic set and pinned in `backend/tests/test_redteam_regression.py`.
* **Blind test 2**. Written after the fixes from blind test 1 froze, and run blind by a separate agent. Its totals are below. This is the honest number for wording nobody has seen yet.

A check-in is **under-triaged** when it is shown as less urgent than it should be. ESI 1 is the most urgent and ESI 5 the least, so a higher number than expected is a miss. An everyday check-in is **over-triaged** when it is shown more urgent than it should be (ESI 1 or 2 for a sprained ankle).

## Results

| Set | Check-ins | Emergencies | Missed before any fix | Missed now | Everyday shown too urgent now | Used to fix the rules |
|---|---|---|---|---|---|---|
| Pinned phrases | 186 | 168 | 155 of 168 | 0 of 168 | 0 of 18 | yes |
| Red-team regression set | 994 | 829 | 792 of 829 | 4 of 829 | 0 of 165 | yes |
| Held-out set | 287 | 190 | 189 of 190 | 49 of 190 | 1 of 97 | no |
| Blind test 1 (now a diagnostic set) | 240 | 160 | 157 of 160 | 39 of 160 | 0 of 80 | yes |
| Blind test 2 | 240 | 160 | not run | 61 of 160 | 4 of 80 | no |

"Before any fix" is the scoring before 2026-10-18: a short list of exact English phrases, and a paperwork word like "refill" could override everything else. So "I can't breathe and need a refill of my inhaler" was shown as ESI 5.

Now, the score shown is always the most urgent of the model and the safety rules. The paperwork rule only applies when nothing else is urgent. The rules read the app's other languages for the most dangerous problems, in their own script and typed in Latin letters, and they notice common ways a patient says a red flag is not happening ("no chest pain", "no tengo dolor de pecho", "胸口也不痛"). A check-in the rules recognize as another language is held at ESI 3 when no AI translation is available, so a nurse reads it soon.

## What the held-out set tells us

Keyword rules catch the pinned and red-team phrases because we wrote rules for them. On new wording they miss more: 49 of 190 held-out emergencies are still shown as less urgent than they should be. That is why the check-in also asks the patient to tap any red flag from a short list (for example "Hard to breathe" or "Chest pain, pressure or tightness"). Any tap sets ESI 2 or more urgent, whatever words were typed and in any language. With an AI key, an AI check reads the patient's words for the same red flags, and it can only raise the score. The AI check's accuracy has not been measured.

`backend/tests/test_redteam_regression.py` checks a harder case than this table: it forces the model to say ESI 5, so the rules alone must carry every red-team emergency.

## Blind test 1, now a diagnostic set

The blind run went through the full app (start-intake, transcribe, intake) with no AI key and the trained model on. It found two kinds of problems: emergencies described in words the rules did not know, and false alarms from words the rules read without noticing they were denied or in the past ("no thoughts of hurting myself" showed the 988 crisis line, "never blacked out", chest pain the patient said they did not have, and a teen who "watched a stroke video" shown ESI 1). We then fixed the rules by category, not phrase by phrase, and wrote fresh phrases for each category, both ways, in the tests. The "now" column is this script's run, in process, with the same scoring the app uses. Because the fixes used this set, the "now" column is no longer a blind number.

| Measure | Blind run, before these fixes | Now |
|---|---|---|
| Emergencies shown less urgent than expected, from the words alone | 58 of 160 | 39 of 160 |
| Emergencies shown ESI 3 or calmer, from the words alone | 53 of 160 | 34 of 160 |
| Emergencies shown ESI 3 or calmer, with honest checklist answers | 21 of 160 | 18 of 160 |
| Everyday check-ins shown ESI 1 or 2 | 8 of 80 | 0 of 80 |

## Blind test 2

Run 2026-10-19. 240 check-ins (160 emergencies, 80 everyday) in English, Spanish, Chinese, Hindi, Arabic and Vietnamese, frozen before the run (sha256 8277960b8475ed569d38b582d6ec98e67c1ad5ccc8bfd0b1e95d58a718081617). Each went through the full app (start-intake, transcribe, intake) with no AI key and the trained model on, and two runs gave identical results. "Shown less urgent than expected" counts an expected ESI 1 shown at ESI 2.

| Measure | Result |
|---|---|
| Emergencies shown less urgent than expected, from the words alone | 61 of 160 |
| Emergencies shown ESI 3 or calmer, from the words alone | 43 of 160 |
| Emergencies shown ESI 3 or calmer, with honest checklist answers | 17 of 160 |
| Everyday check-ins shown ESI 1 or 2 | 4 of 80 |

## Blind test 2 in detail (written by hand)

This section was written by hand from the blind test 2 run, because `scripts/red_flag_report.py`
keeps only the totals above. Running the script again removes this section, so copy it back
afterwards.

**Why this is the honest number.** Blind test 1 was blind when it ran: 53 of its 160
emergencies were missed from the words alone, and 8 of its 80 everyday check-ins were shown
too urgent. Its misses were then used to fix general gaps in the rules: denials ("no chest
pain" in other languages, "never blacked out", "no thoughts of hurting myself"), "not
breathing", swallowed pills, poisons and batteries, and suicide plans. The checklist also got
a tenth item, "Swallowed something dangerous, like pills, poison or a battery". So blind test
1 is now a diagnostic set. Blind test 2 was written by a separate Claude Code agent after
those fixes froze, and nothing in it was used to change the rules.

**How it ran.** 240 check-ins: 160 emergencies and 80 everyday complaints. English has 100
emergencies and 50 everyday ones; Spanish, Chinese, Hindi, Arabic and Vietnamese have 12 and
6 each. The case file was frozen before the run (sha256
`8277960b8475ed569d38b582d6ec98e67c1ad5ccc8bfd0b1e95d58a718081617`). Each check-in went
through the full app in process (start-intake, then transcribe, then intake) with no AI key,
no follow-up answers and the trained model on (5 folds). The whole run was done twice, and
both runs gave identical results. The case file and the run are not in this repository.

How we count:

* **Missed:** an emergency shown at ESI 3, 4 or 5.
* **Less urgent than expected:** an emergency shown at a higher ESI number than expected.
  This also counts an expected ESI 1 shown at ESI 2.
* **Everyday shown too urgent:** an everyday complaint shown at ESI 1 or 2.
* **With the checklist:** truthful checklist answers, sent only when `/transcribe` asked for
  the checklist, as the app does. Everyday check-ins answered "None of these".

| Measure | Words only | With honest checklist answers |
|---|---|---|
| Emergencies missed (ESI 3 or calmer) | 43 of 160 | 17 of 160 |
| Emergencies shown less urgent than expected | 61 of 160 | 42 of 160 |
| Expected ESI 1, shown at ESI 1 | 16 of 41 | 16 of 41 |
| Everyday check-ins shown ESI 1 or 2 | 4 of 80 | 4 of 80 |

The checklist was shown for 43 of the 160 emergencies and 76 of the 80 everyday check-ins.
For the other 117 emergencies the rules had already set ESI 1 or 2, so the app skipped it.
The checklist can only lift a score to ESI 2, so it cannot move an ESI 1 emergency shown at
ESI 2: with the checklist, 25 of the 41 expected ESI 1 emergencies were shown at ESI 2, and
none at ESI 3 or calmer.

### By language

| Language | Emergencies | Everyday | Missed, words only | Missed, with checklist | Less urgent than expected, words only | Less urgent than expected, with checklist | Expected ESI 1 shown at ESI 1 | Everyday shown too urgent |
|---|---|---|---|---|---|---|---|---|
| English | 100 | 50 | 26 | 12 | 39 | 27 | 11 of 26 | 3 |
| Spanish | 12 | 6 | 2 | 0 | 3 | 2 | 1 of 3 | 0 |
| Chinese | 12 | 6 | 4 | 2 | 5 | 4 | 1 of 3 | 0 |
| Hindi | 12 | 6 | 5 | 1 | 6 | 4 | 0 of 3 | 0 |
| Arabic | 12 | 6 | 3 | 1 | 4 | 2 | 2 of 3 | 0 |
| Vietnamese | 12 | 6 | 3 | 1 | 4 | 3 | 1 of 3 | 1 |
| All | 160 | 80 | 43 | 17 | 61 | 42 | 16 of 41 | 4 |

The ESI 1 count and the everyday count are the same with and without the checklist.

### What is still missed with the checklist (17)

For 125 of the 160 emergencies, at least one checklist item honestly applies. The words alone
missed 26 of them, and with honest checklist answers none of them is missed. Every one of the
17 that are still missed is an emergency for which the blind evaluator marked no checklist
item as applying:

* English (12, all shown ESI 3 to 5): loss of sight on one side, a stroke that shows up as
  sudden dizziness and trouble walking, the worst back pain with numbness and loss of bladder
  control, two pregnancy warnings (a bad headache, flashing lights and swelling at 34 weeks;
  no baby movement at 32 weeks), a 9 month old screaming on and off with red jelly-like
  stool, a likely stomach bleed after a week of heavy ibuprofen, neck pain with tingling hands
  after a rollover crash, a fever with chills a week after chemotherapy, a sudden painful
  blurry eye with halos and vomiting, sudden loss of sight in one eye, and a rock-hard belly 4
  days after surgery.
* Other languages (5, all held at ESI 3 for a nurse to read): a pregnancy headache with
  flashing lights and swelling, and the sudden worst headache of a life with vomiting (both
  Chinese), vomiting blood with dizziness on standing (Hindi), the sudden worst headache with
  vomiting (Arabic), and a head injury with headache and vomiting in someone on a blood
  thinner (Vietnamese).

### Everyday check-ins shown too urgent (4)

| Phrase | Language | Expected | Shown |
|---|---|---|---|
| My wrist hurts after I fell off my skateboard, it's swollen. I didn't hit my head or pass out. | English | ESI 4 | ESI 2 |
| I'm not having a stroke or anything, my face is fine, I just have a cold sore on my lip that hurts | English | ESI 5 | ESI 1 |
| Hives on my belly after a new laundry soap. No swelling of my lips or tongue and breathing fine. | English | ESI 4 | ESI 2 |
| Đau răng muốn chết luôn, hai ngày rồi (a toothache that "hurts so much I could die", a figure of speech) | Vietnamese | ESI 5 | ESI 2, with the 988 crisis card |

Three are denials the rules did not notice, and one is a figure of speech. The checklist
cannot fix these, because it can only raise a score.

### What blind test 2 does not tell us

It ran with no AI key, so it says nothing about the AI red-flag check or AI translation. Its
check-ins were written by a Claude Code agent, not collected from patients, and no native
speaker or clinician has checked them or their expected levels.

## Red-team emergencies still missed (4)

| Phrase | Language | Expected | Before | After |
|---|---|---|---|---|
| grease fire burned my face and my voice is getting hoarse | English | ESI 1 | ESI 4 | ESI 2 |
| i got stabbed | English | ESI 1 | ESI 4 | ESI 2 |
| fell from a ladder onto my back cant feel my legs | English | ESI 1 | ESI 4 | ESI 2 |
| the baby is coming i can see the head | English | ESI 1 | ESI 4 | ESI 2 |

## Red-team everyday check-ins shown too urgent (0)

None.

## Held-out emergencies still missed (49)

| Phrase | Language | Expected | Before | After |
|---|---|---|---|---|
| the baby wont stop vomiting green stuff | English | ESI 2 or more urgent | ESI 4 | ESI 4 |
| i accidentally took my blood thinner twice and now im bleeding from my gums and nose and it wont stop | English | ESI 2 or more urgent | ESI 4 | ESI 4 |
| i think my appendix burst, the pain is unbearable | English | ESI 2 or more urgent | ESI 3 | ESI 3 |
| my son got bit by a dog on his face and theres a big flap of skin | English | ESI 3 or more urgent | ESI 4 | ESI 4 |
| my throat feels like its closing and i feel itchy everywhere | English | ESI 2 or more urgent | ESI 5 | ESI 5 |
| i overdid it on my insulin and now im sweaty and shaky and cant think straight | English | ESI 2 or more urgent | ESI 4 | ESI 4 |
| im 8 months pregnant and my hands and face are super swollen and i have a headache | English | ESI 2 or more urgent | ESI 4 | ESI 4 |
| i got punched in the throat in a fight and its hard to swallow and my voice is weird | English | ESI 2 or more urgent | ESI 4 | ESI 4 |
| my friend took acid and is freaking out and running into traffic | English | ESI 2 or more urgent | ESI 4 | ESI 4 |
| my baby fell off the bed and has a soft lump on her head and keeps throwing up | English | ESI 2 or more urgent | ESI 4 | ESI 4 |
| i ate some wild mushrooms and now im vomiting and my stomach is cramping really bad | English | ESI 2 or more urgent | ESI 4 | ESI 4 |
| i cant stop shaking and i feel like bugs are crawling on me, i ran out of my xanax | English | ESI 2 or more urgent | ESI 4 | ESI 4 |
| my teenage son said he took a bottle of something from the medicine cabinet | English | ESI 2 or more urgent | ESI 4 | ESI 4 |
| i have a migraine but this one is different, worst ever and my neck is stiff | English | ESI 2 or more urgent | ESI 3 | ESI 3 |
| my husband is grabbing his chest and cant talk | English | ESI 1 | ESI 4 | ESI 2 |
| my mom has a really bad nosebleed and it wont stop after 30 minutes and she takes eliquis | English | ESI 2 or more urgent | ESI 5 | ESI 5 |
| no puedo agarrar aire | Spanish | ESI 2 or more urgent | ESI 4 | ESI 3 |
| se corto y esta saliendo un chorro de sangre | Spanish | ESI 2 or more urgent | ESI 3 | ESI 3 |
| 胸口像被石头压着 | Chinese | ESI 2 or more urgent | ESI 4 | ESI 3 |
| 血流得到处都是 | Chinese | ESI 2 or more urgent | ESI 4 | ESI 3 |
| दादाजी का मुंह एक तरफ झुक गया है | Hindi | ESI 2 or more urgent | ESI 4 | ESI 3 |
| صدري مضغوط وما اقدر اتحمل | Arabic | ESI 2 or more urgent | ESI 4 | ESI 3 |
| ابوي فجأة ما يقدر يحرك يده اليمين | Arabic | ESI 2 or more urgent | ESI 4 | ESI 3 |
| امي طاحت وما تتحرك ولا ترد | Arabic | ESI 2 or more urgent | ESI 4 | ESI 3 |
| elle a la bouche qui tombe et elle n'arrive plus a parler | French | ESI 2 or more urgent | ESI 4 | ESI 3 |
| в груди сильная боль | Russian | ESI 2 or more urgent | ESI 4 | ESI 3 |
| сильно идёт кровь | Russian | ESI 2 or more urgent | ESI 4 | ESI 3 |
| у мамы опустился угол рта | Russian | ESI 2 or more urgent | ESI 4 | ESI 3 |
| 息が吸えない | Japanese | ESI 2 or more urgent | ESI 4 | ESI 3 |
| 出血がすごい | Japanese | ESI 2 or more urgent | ESI 4 | ESI 3 |
| 意識がなくて呼吸がおかしい | Japanese | ESI 2 or more urgent | ESI 4 | ESI 3 |
| 가슴이 터질 것 같이 아파요 | Korean | ESI 2 or more urgent | ESI 4 | ESI 3 |
| 숨이 안 쉬어져요 | Korean | ESI 2 or more urgent | ESI 4 | ESI 3 |
| tôi đau thắt ngực | Vietnamese | ESI 2 or more urgent | ESI 4 | ESI 3 |
| không thở nổi | Vietnamese | ESI 2 or more urgent | ESI 4 | ESI 3 |
| ông tôi bị méo mặt, nói không được | Vietnamese | ESI 2 or more urgent | ESI 4 | ESI 3 |
| ich ersticke | German | ESI 2 or more urgent | ESI 5 | ESI 3 |
| perdo molto sangue | Italian | ESI 2 or more urgent | ESI 4 | ESI 3 |
| chcę się zabić | Polish | ESI 2 or more urgent | ESI 4 | ESI 3 |
| خونریزی دارم بند نمیاد | Persian | ESI 2 or more urgent | ESI 4 | ESI 3 |
| سانس نہیں لے پا رہا | Urdu | ESI 2 or more urgent | ESI 4 | ESI 3 |
| dada saya terasa seperti ditekan | Indonesian | ESI 2 or more urgent | ESI 4 | ESI 3 |
| darah keluar terus tidak berhenti | Indonesian | ESI 2 or more urgent | ESI 4 | ESI 3 |
| wajah ayah saya tiba tiba miring | Indonesian | ESI 2 or more urgent | ESI 4 | ESI 3 |
| biglang tumabingi ang mukha ni lolo | Filipino | ESI 2 or more urgent | ESI 4 | ESI 3 |
| রক্ত পড়া থামছে না | Bengali | ESI 2 or more urgent | ESI 4 | ESI 3 |
| mi abuelo esta desorientado desde hoy | Spanish | ESI 2 or more urgent | ESI 4 | ESI 3 |
| بنتي عمرها 3 أسابيع وحرارتها 38 | Arabic | ESI 2 or more urgent | ESI 4 | ESI 3 |
| 임신 35주인데 아기가 안 움직여요 | Korean | ESI 2 or more urgent | ESI 4 | ESI 3 |

## Held-out everyday check-ins shown too urgent (1)

| Phrase | Language | Expected | Before | After |
|---|---|---|---|---|
| i bruised my ribs at football and it hurts to breathe deep | English | ESI 3 to 5 | ESI 3 | ESI 2 |

## Blind test 1 emergencies still missed (39)

| Phrase | Language | Expected | Before | After |
|---|---|---|---|---|
| the defibrillator thing they put in me just went off and shocked me twice in ten minutes | English | ESI 2 or more urgent | ESI 4 | ESI 4 |
| the room is spinning, I cant walk straight, and Im seeing two of everything, it all came on at once about an hour ago | English | ESI 2 or more urgent | ESI 4 | ESI 4 |
| i woke up and half my face wont move and my speech sounds off | English | ESI 2 or more urgent | ESI 5 | ESI 5 |
| Uncle Ray suddenly cant find his words, he knows what he wants to say but it comes out as gibberish | English | ESI 2 or more urgent | ESI 3 | ESI 3 |
| ate shrimp pasta and now my tongue feels huge and my throat is closing up | English | ESI 1 | ESI 4 | ESI 2 |
| allergic to cashews and I think there were some in my thai food, now I'm wheezing and throwing up | English | ESI 2 or more urgent | ESI 4 | ESI 4 |
| We were riding home from the lake and my buddy laid his bike down on the highway, maybe 50 mph, and slid into the guardrail. He got up and said he was fine so we drove him here ourselves, but in the car his belly started getting hard and swollen and now he's really pale and keeps saying he's cold. | English | ESI 2 or more urgent | ESI 4 | ESI 4 |
| my son is having a seizure right now and its been going for like 5 minutes | English | ESI 1 | ESI 3 | ESI 2 |
| he's 76 and he's been vomiting what looks like coffee grounds and his poop is black | English | ESI 2 or more urgent | ESI 4 | ESI 4 |
| I had chemo 8 days ago and now I have a fever of 101.5 and chills | English | ESI 2 or more urgent | ESI 4 | ESI 4 |
| I had part of my bowel taken out four days ago and they sent me home yesterday. Since this morning the belly pain has been getting a lot worse instead of better, I have a fever of 102, and my heart feels like it's racing even lying down. | English | ESI 2 or more urgent | ESI 4 | ESI 4 |
| my belly is rock hard and swollen, I havent pooped or passed gas in 3 days, Im puking green and the pain is a 9 | English | ESI 2 or more urgent | ESI 4 | ESI 4 |
| the pain in my lower right belly got really bad, then suddenly eased up, and now my whole belly hurts and I have a fever | English | ESI 2 or more urgent | ESI 4 | ESI 4 |
| got splashed in both eyes with drain cleaner at work | English | ESI 2 or more urgent | ESI 4 | ESI 4 |
| electrician, got zapped by 480 volts, theres a burn on my hand and my heart keeps fluttering | English | ESI 2 or more urgent | ESI 4 | ESI 4 |
| blood pressure was 220/130 on the pharmacy machine and I have a pounding headache and blurry vision | English | ESI 2 or more urgent | ESI 4 | ESI 4 |
| A mi papá se le durmió la mitad de la cara y no puede hablar bien, empezó de repente | Spanish | ESI 2 or more urgent | ESI 4 | ESI 3 |
| Tengo 8 semanas de embarazo, me duele muchísimo el lado derecho de la panza y estoy mareada | Spanish | ESI 2 or more urgent | ESI 3 | ESI 3 |
| Soy diabético, tengo el azúcar en 450, vomito mucho y respiro raro, me siento muy débil | Spanish | ESI 2 or more urgent | ESI 5 | ESI 3 |
| Me picó una abeja y se me hinchó toda la cara, siento la garganta apretada | Spanish | ESI 1 | ESI 4 | ESI 3 |
| Mi abuelo de 80 años tiene fiebre, está muy dormido y no nos reconoce | Spanish | ESI 2 or more urgent | ESI 4 | ESI 3 |
| mi hijo de 12 años tiene un dolor horrible en un testículo desde hace dos horas y está vomitando | Spanish | ESI 2 or more urgent | ESI 3 | ESI 3 |
| 我奶奶刚才吃饭的时候突然筷子拿不住了，嘴角歪了，说话含糊 | Chinese | ESI 2 or more urgent | ESI 4 | ESI 3 |
| 宝宝出生才五十天，摸着很烫，量了38.6度，一直哭 | Chinese | ESI 2 or more urgent | ESI 4 | ESI 3 |
| 撕裂一样的疼，从胸口一直穿到后背，我有高血压 | Chinese | ESI 2 or more urgent | ESI 4 | ESI 3 |
| 被蜜蜂蜇了以后全身起疹子，嘴唇肿了，喉咙发紧，喘不过气 | Chinese | ESI 1 | ESI 4 | ESI 2 |
| 我做完化疗一个星期，现在发烧39度，一直发抖 | Chinese | ESI 2 or more urgent | ESI 4 | ESI 3 |
| खेत में सांप ने काट लिया, पैर सूज रहा है और चक्कर आ रहे हैं | Hindi | ESI 2 or more urgent | ESI 4 | ESI 3 |
| बहुत गर्मी में काम कर रहा था, अचानक गिर पड़ा, अब बहकी-बहकी बातें कर रहा है, बदन आग जैसा गर्म है | Hindi | ESI 2 or more urgent | ESI 4 | ESI 3 |
| أحس بضغط قوي على صدري من نص ساعة، وعرقان، والألم رايح لفكي | Arabic | ESI 2 or more urgent | ESI 4 | ESI 3 |
| أمي فجأة وجهها مال على جهة وما تقدر ترفع يدها اليسار | Arabic | ESI 2 or more urgent | ESI 4 | ESI 3 |
| بنتي عمرها ٦ أسابيع وحرارتها ٣٨٫٤ وما ترضع | Arabic | ESI 2 or more urgent | ESI 4 | ESI 3 |
| صار لي حادث سيارة قوي، بطني يوجعني مرة وأحس بدوخة | Arabic | ESI 2 or more urgent | ESI 4 | ESI 3 |
| أكلت فول سوداني وحلقي يتسكر وصعب أتنفس | Arabic | ESI 1 | ESI 4 | ESI 2 |
| صداع مفاجئ قوي جداً، أسوأ صداع في حياتي، وتقيأت | Arabic | ESI 2 or more urgent | ESI 4 | ESI 3 |
| Con tôi bị sốt xuất huyết, hôm nay chảy máu chân răng, chảy máu cam không cầm được, người lạnh | Vietnamese | ESI 2 or more urgent | ESI 4 | ESI 3 |
| Ông tôi 82 tuổi, sốt cao, lơ mơ, không nhận ra con cháu | Vietnamese | ESI 2 or more urgent | ESI 4 | ESI 3 |
| toi bi kho tho, hong sung len sau khi an tom | Vietnamese | ESI 1 | ESI 4 | ESI 2 |
| Đột nhiên đau đầu dữ dội nhất trong đời, còn bị nôn | Vietnamese | ESI 2 or more urgent | ESI 4 | ESI 3 |

## Blind test 1 everyday check-ins shown too urgent (0)

None.

## Every pinned phrase

| Phrase | Language | Expected | Before | After |
|---|---|---|---|---|
| Crushing chest pain down my left arm and I'm sweating | English | ESI 2 or more urgent | ESI 2 | ESI 2 |
| Me duele mucho el pecho y no puedo respirar | Spanish | ESI 2 or more urgent | ESI 4 (miss) | ESI 2 |
| My 3 year old has a fever of 104 and is very sleepy | English | ESI 2 or more urgent | ESI 4 (miss) | ESI 2 |
| I feel like I want to end my life | English | ESI 2 or more urgent | ESI 4 (miss) | ESI 2 |
| I have been feeling suicidal and want to end my life | English | ESI 2 or more urgent | ESI 2 | ESI 2 |
| I took a whole bottle of tylenol | English | ESI 2 or more urgent | ESI 4 (miss) | ESI 2 |
| he fell off a ladder and hit his head and is confused | English | ESI 2 or more urgent | ESI 4 (miss) | ESI 2 |
| my son is 2 and has a fever of 104 and is very sleepy | English | ESI 2 or more urgent | ESI 4 (miss) | ESI 2 |
| I can't breathe | English | ESI 2 or more urgent | ESI 4 (miss) | ESI 2 |
| my chest hurts a lot and I can't breathe | English | ESI 2 or more urgent | ESI 5 (miss) | ESI 2 |
| my face is drooping and my left arm is weak and my speech is slurred | English | ESI 1 | ESI 3 (miss) | ESI 1 |
| bad headache and fever for two days with a stiff neck | English | ESI 2 or more urgent | ESI 4 (miss) | ESI 2 |
| I cut my hand on glass and it won't stop bleeding. | English | ESI 2 or more urgent | ESI 4 (miss) | ESI 2 |
| I am 30 weeks pregnant and bleeding | English | ESI 2 or more urgent | ESI 4 (miss) | ESI 2 |
| my throat is swelling after eating peanuts | English | ESI 2 or more urgent | ESI 5 (miss) | ESI 2 |
| I fainted at work and need a work note | English | ESI 2 or more urgent | ESI 5 (miss) | ESI 2 |
| I can’t breathe and need a refill of my inhaler | English | ESI 2 or more urgent | ESI 5 (miss) | ESI 2 |
| I need a refill of my blood thinner, my gums keep bleeding and I feel dizzy and faint | English | ESI 2 or more urgent | ESI 5 (miss) | ESI 2 |
| my husband collapsed, he is not breathing | English | ESI 1 | ESI 1 | ESI 1 |
| I can't breathe well and my lips feel tingly | English | ESI 2 or more urgent | ESI 4 (miss) | ESI 2 |
| I'm bleeding a lot | English | ESI 2 or more urgent | ESI 4 (miss) | ESI 2 |
| worst headache of my life, came on suddenly an hour ago | English | ESI 2 or more urgent | ESI 2 | ESI 2 |
| Tengo un dolor fuerte en el pecho y me cuesta respirar | Spanish | ESI 2 or more urgent | ESI 5 (miss) | ESI 2 |
| मेरे सीने में बहुत दर्द है और सांस लेने में तकलीफ है | Hindi | ESI 2 or more urgent | ESI 4 (miss) | ESI 2 |
| 胸口很痛，喘不过气 | Chinese | ESI 2 or more urgent | ESI 4 (miss) | ESI 2 |
| عندي ألم شديد في صدري ولا أستطيع التنفس | Arabic | ESI 2 or more urgent | ESI 4 (miss) | ESI 2 |
| I'm having a heart attack | English | ESI 2 or more urgent | ESI 4 (miss) | ESI 2 |
| there is a lot of pressure in my chest | English | ESI 2 or more urgent | ESI 4 (miss) | ESI 2 |
| It's really hard for me to breathe | English | ESI 2 or more urgent | ESI 5 (miss) | ESI 2 |
| I can barely breathe | English | ESI 2 or more urgent | ESI 4 (miss) | ESI 2 |
| I'm not breathing well | English | ESI 2 or more urgent | ESI 1 | ESI 2 |
| he is gasping for air | English | ESI 1 | ESI 4 (miss) | ESI 1 |
| my baby's lips are turning blue | English | ESI 1 | ESI 5 (miss) | ESI 1 |
| my daughter is choking | English | ESI 1 | ESI 1 | ESI 1 |
| my wife passed out and won't wake up | English | ESI 1 | ESI 4 (miss) | ESI 1 |
| I think I'm having a stroke | English | ESI 1 | ESI 1 | ESI 1 |
| sudden weakness on the left side of my body | English | ESI 1 | ESI 1 | ESI 1 |
| my face feels numb on one side | English | ESI 1 | ESI 1 | ESI 1 |
| my lips and tongue are swollen | English | ESI 2 or more urgent | ESI 4 (miss) | ESI 2 |
| I'm having an allergic reaction and my throat feels tight | English | ESI 2 or more urgent | ESI 2 | ESI 2 |
| I'm pregnant and spotting with bad cramps | English | ESI 2 or more urgent | ESI 4 (miss) | ESI 2 |
| I passed out in the shower | English | ESI 2 or more urgent | ESI 4 (miss) | ESI 2 |
| I feel like I'm going to faint | English | ESI 2 or more urgent | ESI 4 (miss) | ESI 2 |
| I hit my head and threw up twice | English | ESI 2 or more urgent | ESI 4 (miss) | ESI 2 |
| my 4 year old has a fever and is hard to wake up | English | ESI 2 or more urgent | ESI 4 (miss) | ESI 2 |
| my 6 week old baby has a fever | English | ESI 2 or more urgent | ESI 4 (miss) | ESI 2 |
| I don't want to live anymore | English | ESI 2 or more urgent | ESI 5 (miss) | ESI 2 |
| I want to kill myself | English | ESI 2 or more urgent | ESI 2 | ESI 2 |
| I want to die | English | ESI 2 or more urgent | ESI 4 (miss) | ESI 2 |
| I took too many pills on purpose | English | ESI 2 or more urgent | ESI 2 | ESI 2 |
| I took 30 of my sleeping pills | English | ESI 2 or more urgent | ESI 4 (miss) | ESI 2 |
| my toddler swallowed a laundry pod | English | ESI 2 or more urgent | ESI 5 (miss) | ESI 2 |
| my son is having a seizure | English | ESI 2 or more urgent | ESI 3 (miss) | ESI 2 |
| I was shot in the leg | English | ESI 1 | ESI 4 (miss) | ESI 1 |
| my finger got cut off by a saw | English | ESI 1 | ESI 1 | ESI 1 |
| I'm coughing up blood | English | ESI 2 or more urgent | ESI 4 (miss) | ESI 2 |
| my stiff neck and fever started this morning | English | ESI 2 or more urgent | ESI 4 (miss) | ESI 2 |
| Me corté la mano y no para de sangrar | Spanish | ESI 2 or more urgent | ESI 4 (miss) | ESI 2 |
| Ya no quiero vivir | Spanish | ESI 2 or more urgent | ESI 4 (miss) | ESI 2 |
| Mi papá tiene la cara caída y no puede hablar bien | Spanish | ESI 1 | ESI 4 (miss) | ESI 1 |
| Mi esposo está inconsciente | Spanish | ESI 1 | ESI 4 (miss) | ESI 1 |
| Mi hijo de 2 años tiene fiebre y está muy dormido | Spanish | ESI 2 or more urgent | ESI 4 (miss) | ESI 2 |
| 我胸口很痛 | Chinese | ESI 2 or more urgent | ESI 4 (miss) | ESI 2 |
| 我喘不过气 | Chinese | ESI 2 or more urgent | ESI 4 (miss) | ESI 2 |
| 伤口一直流血，流血不止 | Chinese | ESI 2 or more urgent | ESI 4 (miss) | ESI 2 |
| 我想自杀 | Chinese | ESI 2 or more urgent | ESI 4 (miss) | ESI 2 |
| 我爸爸嘴歪了，说话不清 | Chinese | ESI 1 | ESI 4 (miss) | ESI 1 |
| 我妈妈昏迷了 | Chinese | ESI 1 | ESI 4 (miss) | ESI 1 |
| لا أستطيع التنفس | Arabic | ESI 2 or more urgent | ESI 4 (miss) | ESI 2 |
| عندي نزيف شديد | Arabic | ESI 2 or more urgent | ESI 4 (miss) | ESI 2 |
| أريد أن أموت | Arabic | ESI 2 or more urgent | ESI 4 (miss) | ESI 2 |
| أبي عنده جلطة دماغية | Arabic | ESI 1 | ESI 4 (miss) | ESI 1 |
| زوجي فاقد الوعي | Arabic | ESI 1 | ESI 4 (miss) | ESI 1 |
| मुझे साँस लेने में तकलीफ है | Hindi | ESI 2 or more urgent | ESI 4 (miss) | ESI 2 |
| बहुत ज्यादा खून बह रहा है | Hindi | ESI 2 or more urgent | ESI 4 (miss) | ESI 2 |
| मैं आत्महत्या करना चाहता हूं | Hindi | ESI 2 or more urgent | ESI 4 (miss) | ESI 2 |
| मेरे पिता को लकवा मार गया है | Hindi | ESI 1 | ESI 4 (miss) | ESI 1 |
| मेरी मां बेहोश हैं | Hindi | ESI 1 | ESI 4 (miss) | ESI 1 |
| Tôi bị đau ngực | Vietnamese | ESI 2 or more urgent | ESI 4 (miss) | ESI 2 |
| Tôi khó thở | Vietnamese | ESI 2 or more urgent | ESI 4 (miss) | ESI 2 |
| Vết thương chảy máu không ngừng | Vietnamese | ESI 2 or more urgent | ESI 4 (miss) | ESI 2 |
| Tôi muốn chết | Vietnamese | ESI 2 or more urgent | ESI 4 (miss) | ESI 2 |
| Bố tôi bị méo miệng và yếu nửa người | Vietnamese | ESI 1 | ESI 4 (miss) | ESI 1 |
| Mẹ tôi bị bất tỉnh | Vietnamese | ESI 1 | ESI 4 (miss) | ESI 1 |
| J'ai une douleur dans la poitrine | French | ESI 2 or more urgent | ESI 3 (miss) | ESI 2 |
| Je n’arrive pas à respirer | French | ESI 2 or more urgent | ESI 5 (miss) | ESI 2 |
| Je saigne beaucoup et ça ne s'arrête pas | French | ESI 2 or more urgent | ESI 4 (miss) | ESI 2 |
| Je veux mourir | French | ESI 2 or more urgent | ESI 5 (miss) | ESI 2 |
| Mon père a le visage paralysé d'un côté | French | ESI 1 | ESI 3 (miss) | ESI 1 |
| Ma mère a perdu connaissance | French | ESI 1 | ESI 4 (miss) | ESI 1 |
| Estou com uma dor forte no peito | Portuguese | ESI 2 or more urgent | ESI 4 (miss) | ESI 2 |
| Não consigo respirar | Portuguese | ESI 2 or more urgent | ESI 5 (miss) | ESI 2 |
| Estou sangrando muito | Portuguese | ESI 2 or more urgent | ESI 4 (miss) | ESI 2 |
| Eu quero morrer | Portuguese | ESI 2 or more urgent | ESI 5 (miss) | ESI 2 |
| Meu pai está com a boca torta e a fala enrolada | Portuguese | ESI 1 | ESI 4 (miss) | ESI 1 |
| Minha mãe está inconsciente | Portuguese | ESI 1 | ESI 4 (miss) | ESI 1 |
| У меня сильная боль в груди | Russian | ESI 2 or more urgent | ESI 4 (miss) | ESI 2 |
| Я не могу дышать | Russian | ESI 2 or more urgent | ESI 4 (miss) | ESI 2 |
| Кровь не останавливается | Russian | ESI 2 or more urgent | ESI 4 (miss) | ESI 2 |
| Я хочу умереть | Russian | ESI 2 or more urgent | ESI 4 (miss) | ESI 2 |
| У отца перекосило лицо | Russian | ESI 1 | ESI 4 (miss) | ESI 1 |
| Муж без сознания | Russian | ESI 1 | ESI 4 (miss) | ESI 1 |
| 가슴이 너무 아파요 | Korean | ESI 2 or more urgent | ESI 4 (miss) | ESI 2 |
| 숨을 쉴 수 없어요 | Korean | ESI 2 or more urgent | ESI 4 (miss) | ESI 2 |
| 피가 멈추지 않아요 | Korean | ESI 2 or more urgent | ESI 4 (miss) | ESI 2 |
| 죽고 싶어요 | Korean | ESI 2 or more urgent | ESI 4 (miss) | ESI 2 |
| 아버지 얼굴이 한쪽으로 처졌어요 | Korean | ESI 1 | ESI 4 (miss) | ESI 1 |
| 남편이 의식이 없어요 | Korean | ESI 1 | ESI 4 (miss) | ESI 1 |
| Masakit ang dibdib ko | Filipino | ESI 2 or more urgent | ESI 4 (miss) | ESI 2 |
| Hindi ako makahinga | Filipino | ESI 2 or more urgent | ESI 4 (miss) | ESI 2 |
| Ayaw tumigil ang pagdurugo | Filipino | ESI 2 or more urgent | ESI 3 (miss) | ESI 2 |
| Gusto ko nang mamatay | Filipino | ESI 2 or more urgent | ESI 4 (miss) | ESI 2 |
| Tabingi ang mukha ng tatay ko | Filipino | ESI 1 | ESI 4 (miss) | ESI 1 |
| Nawalan ng malay ang nanay ko | Filipino | ESI 1 | ESI 4 (miss) | ESI 1 |
| میرے سینے میں شدید درد ہے | Urdu | ESI 2 or more urgent | ESI 4 (miss) | ESI 2 |
| مجھے سانس لینے میں تکلیف ہے | Urdu | ESI 2 or more urgent | ESI 4 (miss) | ESI 2 |
| بہت زیادہ خون بہہ رہا ہے | Urdu | ESI 2 or more urgent | ESI 4 (miss) | ESI 2 |
| میں خودکشی کرنا چاہتا ہوں | Urdu | ESI 2 or more urgent | ESI 4 (miss) | ESI 2 |
| میرے والد کو فالج ہو گیا ہے | Urdu | ESI 1 | ESI 4 (miss) | ESI 1 |
| میری امی بے ہوش ہیں | Urdu | ESI 1 | ESI 4 (miss) | ESI 1 |
| درد شدید در قفسه سینه دارم | Persian | ESI 2 or more urgent | ESI 4 (miss) | ESI 2 |
| نمی‌توانم نفس بکشم | Persian | ESI 2 or more urgent | ESI 4 (miss) | ESI 2 |
| خونریزی شدید دارم | Persian | ESI 2 or more urgent | ESI 4 (miss) | ESI 2 |
| می‌خواهم خودکشی کنم | Persian | ESI 2 or more urgent | ESI 4 (miss) | ESI 2 |
| پدرم سکته مغزی کرده | Persian | ESI 1 | ESI 4 (miss) | ESI 1 |
| مادرم بیهوش شده | Persian | ESI 1 | ESI 4 (miss) | ESI 1 |
| আমার বুকে খুব ব্যথা | Bengali | ESI 2 or more urgent | ESI 4 (miss) | ESI 2 |
| আমার শ্বাস নিতে কষ্ট হচ্ছে | Bengali | ESI 2 or more urgent | ESI 4 (miss) | ESI 2 |
| রক্ত বন্ধ হচ্ছে না | Bengali | ESI 2 or more urgent | ESI 4 (miss) | ESI 2 |
| আমি আত্মহত্যা করতে চাই | Bengali | ESI 2 or more urgent | ESI 4 (miss) | ESI 2 |
| আমার বাবার স্ট্রোক হয়েছে | Bengali | ESI 1 | ESI 4 (miss) | ESI 1 |
| আমার মা অজ্ঞান হয়ে গেছেন | Bengali | ESI 1 | ESI 4 (miss) | ESI 1 |
| 胸が痛いです | Japanese | ESI 2 or more urgent | ESI 4 (miss) | ESI 2 |
| 息ができない | Japanese | ESI 2 or more urgent | ESI 4 (miss) | ESI 2 |
| 血が止まらない | Japanese | ESI 2 or more urgent | ESI 4 (miss) | ESI 2 |
| 死にたい | Japanese | ESI 2 or more urgent | ESI 4 (miss) | ESI 2 |
| 父の顔が歪んで、ろれつが回らない | Japanese | ESI 1 | ESI 4 (miss) | ESI 1 |
| 夫の意識がない | Japanese | ESI 1 | ESI 4 (miss) | ESI 1 |
| Ich habe starke Brustschmerzen | German | ESI 2 or more urgent | ESI 5 (miss) | ESI 2 |
| Ich kann nicht atmen | German | ESI 2 or more urgent | ESI 5 (miss) | ESI 2 |
| Die Wunde blutet sehr stark | German | ESI 2 or more urgent | ESI 4 (miss) | ESI 2 |
| Ich will nicht mehr leben | German | ESI 2 or more urgent | ESI 5 (miss) | ESI 2 |
| Ich glaube, mein Vater hat einen Schlaganfall | German | ESI 1 | ESI 4 (miss) | ESI 1 |
| Mein Mann ist bewusstlos | German | ESI 1 | ESI 4 (miss) | ESI 1 |
| Ho un forte dolore al petto | Italian | ESI 2 or more urgent | ESI 4 (miss) | ESI 2 |
| Non riesco a respirare | Italian | ESI 2 or more urgent | ESI 5 (miss) | ESI 2 |
| Sanguina molto e il sangue non si ferma | Italian | ESI 2 or more urgent | ESI 4 (miss) | ESI 2 |
| Voglio morire | Italian | ESI 2 or more urgent | ESI 5 (miss) | ESI 2 |
| Mia madre ha la bocca storta e non riesce a parlare | Italian | ESI 1 | ESI 4 (miss) | ESI 1 |
| Mio marito è svenuto e non risponde | Italian | ESI 1 | ESI 4 (miss) | ESI 1 |
| Göğüs ağrısı var | Turkish | ESI 2 or more urgent | ESI 4 (miss) | ESI 2 |
| Nefes alamıyorum | Turkish | ESI 2 or more urgent | ESI 5 (miss) | ESI 2 |
| Kanama durmuyor | Turkish | ESI 2 or more urgent | ESI 3 (miss) | ESI 2 |
| Ölmek istiyorum | Turkish | ESI 2 or more urgent | ESI 4 (miss) | ESI 2 |
| Babanın yüzü kaydı ve konuşması bozuldu | Turkish | ESI 1 | ESI 4 (miss) | ESI 1 |
| Annem bilincini kaybetti | Turkish | ESI 1 | ESI 4 (miss) | ESI 1 |
| Mam silny ból w klatce piersiowej | Polish | ESI 2 or more urgent | ESI 4 (miss) | ESI 2 |
| Nie mogę oddychać | Polish | ESI 2 or more urgent | ESI 4 (miss) | ESI 2 |
| Bardzo mocno krwawię | Polish | ESI 2 or more urgent | ESI 5 (miss) | ESI 2 |
| Chcę umrzeć | Polish | ESI 2 or more urgent | ESI 4 (miss) | ESI 2 |
| Mój tata ma opadnięty kącik ust | Polish | ESI 1 | ESI 4 (miss) | ESI 1 |
| Moja mama jest nieprzytomna | Polish | ESI 1 | ESI 5 (miss) | ESI 1 |
| Dada saya sakit sekali | Indonesian | ESI 2 or more urgent | ESI 4 (miss) | ESI 2 |
| Saya sesak napas | Indonesian | ESI 2 or more urgent | ESI 4 (miss) | ESI 2 |
| Darahnya tidak mau berhenti | Indonesian | ESI 2 or more urgent | ESI 4 (miss) | ESI 2 |
| Saya ingin bunuh diri | Indonesian | ESI 2 or more urgent | ESI 4 (miss) | ESI 2 |
| Bicaranya pelo dan wajahnya mencong | Indonesian | ESI 1 | ESI 4 (miss) | ESI 1 |
| Suami saya tidak sadarkan diri | Indonesian | ESI 1 | ESI 4 (miss) | ESI 1 |
| I twisted my ankle playing soccer and it's swollen | English | ESI 4 to 5 | ESI 4 | ESI 4 |
| I need a refill of my blood pressure pills | English | ESI 4 to 5 | ESI 5 | ESI 5 |
| I need a school note | English | ESI 4 to 5 | ESI 5 | ESI 5 |
| I have a mild sore throat | English | ESI 4 to 5 | ESI 5 | ESI 5 |
| I have a small cut on my finger that stopped bleeding | English | ESI 4 to 5 | ESI 4 | ESI 4 |
| I have a faint rash on my arm | English | ESI 4 to 5 | ESI 4 | ESI 4 |
| I stubbed my toe | English | ESI 4 to 5 | ESI 4 | ESI 4 |
| I need a flu shot | English | ESI 4 to 5 | ESI 4 | ESI 4 |
| I need a work note | English | ESI 4 to 5 | ESI 5 | ESI 5 |
| I have a cough and a runny nose | English | ESI 4 to 5 | ESI 5 | ESI 5 |
| I hurt my knee playing basketball | English | ESI 4 to 5 | ESI 5 | ESI 5 |
| I have a toothache | English | ESI 4 to 5 | ESI 4 | ESI 4 |
| Me torcí el tobillo y está hinchado | Spanish | ESI 3 to 5 | ESI 4 | ESI 3 |
| Necesito una receta para mis pastillas de la presión | Spanish | ESI 3 to 5 | ESI 3 | ESI 3 |
| 我头很痛，已经三天了 | Chinese | ESI 3 to 5 | ESI 4 | ESI 3 |
| J'ai mal à la gorge depuis deux jours | French | ESI 3 to 5 | ESI 3 | ESI 3 |
| Tenho uma tosse leve | Portuguese | ESI 3 to 5 | ESI 4 | ESI 3 |
| У меня насморк | Russian | ESI 3 to 5 | ESI 4 | ESI 3 |

## The safety rules

| ESI | Rule | Example |
|---|---|---|
| 1 | Not breathing, not waking up, or turning blue | My husband collapsed, he is not breathing |
| 1 | Severe injury (amputation, gunshot, blood spurting) | He was shot in the chest |
| 1 | Stroke signs (face drooping, slurred speech, one side weak) | My face is drooping and my speech is slurred |
| 1 | Red-flag words in 19 more languages: not breathing, unconscious, stroke | Mi esposo no respira (es) |
| 2 | Chest pain or pressure | Crushing chest pain down my left arm |
| 2 | Cannot breathe or very hard to breathe | I can't breathe |
| 2 | Throat, lips, or tongue swelling (allergic reaction) | My throat is swelling after eating peanuts |
| 2 | Heavy bleeding or bleeding that will not stop | I cut my hand on glass and it won't stop bleeding |
| 2 | Pregnant with bleeding, leaking fluid, bad pain, or another warning sign | I am 30 weeks pregnant and bleeding |
| 2 | Fainted, passed out, or collapsed | I fainted at work |
| 2 | Head injury with confusion, vomiting, or passing out | He fell off a ladder and hit his head and is confused |
| 2 | Stiff neck with fever or headache | Bad headache and fever for two days with a stiff neck |
| 2 | Child under 5 with fever who is very sleepy or hard to wake | My 3 year old has a fever of 104 and is very sleepy |
| 2 | Baby under 3 months with a fever | My 6 week old baby has a fever |
| 2 | Suicidal thoughts or self-harm | I feel like I want to end my life |
| 2 | Overdose or poisoning | I took a whole bottle of tylenol |
| 2 | Seizure | My son had a seizure |
| 2 | One arm or one side weak or numb | My left arm is numb |
| 2 | Other high-risk signs (worst headache, vision loss, serious injury, dangerous readings) | Worst headache of my life, it came on suddenly |
| 2 | New confusion or not acting like themselves | My grandma is suddenly confused and does not know where she is |
| 2 | Thoughts of hurting someone else | I keep having thoughts about hurting someone |
| 2 | Sexual assault or strangulation | I was sexually assaulted last night |
| 2 | Very high blood sugar with vomiting, confusion, or fast breathing | My blood sugar is over 600 and I keep throwing up |
| 2 | Baby under 3 months who will not feed, is very sleepy, or has no wet diapers | My 5 week old will not feed and is very sleepy |
| 2 | Young child not peeing and very sleepy | My 18 month old has not peed all day and is really sleepy |
| 2 | Red-flag words in 19 more languages: chest pain, cannot breathe, heavy bleeding, suicidal thoughts | Me duele mucho el pecho y no puedo respirar (es) |
| 2 | The same red flags typed in Latin letters (Hindi, Arabic, Chinese, Russian, Japanese, Korean, Persian, Bengali) | seene mein dard ho raha hai (Hindi in Latin letters) |
| 3 | Written in another language and no AI translation is available: a nurse reads it | Me torcí el tobillo y está hinchado (es) |
| 5 | Paperwork or refill only, used only when nothing else is urgent | I need a refill of my blood pressure pills |

## The bedside vital-sign floor

After a nurse measures vital signs, these checks can raise the score (never lower it).

| ESI | Check |
|---|---|
| 1 | Unresponsive, or GCS 8 or below |
| 2 | New confusion, drowsiness, or agitation (GCS under 15) |
| 2 | Severe pain, 7 or more out of 10 |
| 2 | Oxygen saturation under 92% |
| 2 | Systolic blood pressure under 90 |
| 2 | Heart rate over 100 (age 8 and up) |
| 2 | Breathing rate over 20 per minute (age 8 and up) |

## Limits

Every check-in in these sets was written with Claude Code, an AI coding assistant, at the team's direction, not by the students themselves: the pinned phrases, the red-team and held-out sets, and both blind sets (each written by a separate Claude Code agent). None was collected from real patients, and none of the phrases, in any language, has been checked by native speakers or clinicians. The expected levels follow the ESI handbook as those agents read it, and a few are judgment calls. Passing these tests does not mean the app is safe for real triage; it is a student demo. The rules are meant to catch the most dangerous words, and a nurse always makes the real decision.
