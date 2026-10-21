r"""Word lists for the red-flag rules in services/triage_rules.py.

This file is data only: misspellings, the red-flag words in the app's 19 other
languages (in their own script and typed in Latin letters), and the words that
tell the rules a patient is denying a symptom. triage_rules.py turns these into
patterns and decides what each match means.

Latin-script lists are written without accents and matched on accent-stripped text;
the rest match normalized text (triage_rules.normalize). Never use \S, \W, \D or \B:
normalize() lowercases every pattern. Vietnamese keeps its tones ("tự tử" vs "từ từ")
with plain-typed forms added. Codes ending in _latn are a language typed in Latin
letters ("seene mein dard").

These words were written with Claude Code at the team's direction and have not been
checked by native speakers. Keyword lists never cover every way a person can describe
an emergency; the red-flag checklist the patient taps is the safety net for that.
"""
from __future__ import annotations

# Common misspellings and dictation splits, folded to the word the English rules know.
TYPOS: dict[str, str] = {
    "breth": "breath", "brethe": "breathe", "breate": "breathe", "breating": "breathing", "breathng": "breathing",
    "brething": "breathing", "breathin": "breathing", "shortnes": "shortness", "cnt": "cant", "2 breathe": "to breathe",
    "can t": "cant", "don t": "dont", "won t": "wont", "isn t": "isnt", "doesn t": "doesnt", "couldn t": "couldnt",
    "pian": "pain", "chest pane": "chest pain", "cheast": "chest", "chesst": "chest", "chestpain": "chest pain",
    "chestpains": "chest pains", "hart attack": "heart attack", "hart attak": "heart attack", "heartattack": "heart attack",
    "attak": "attack", "atack": "attack", "tite": "tight",
    "stoke": "stroke", "strok": "stroke", "droping": "drooping", "slured": "slurred", "sluring": "slurring",
    "unconsious": "unconscious", "unconcious": "unconscious", "unconsius": "unconscious", "unconscous": "unconscious",
    "unresponsve": "unresponsive", "unresponive": "unresponsive", "unresposive": "unresponsive",
    "siezure": "seizure", "seizer": "seizure", "sezure": "seizure", "seisure": "seizure", "seazure": "seizure",
    "siezures": "seizures", "seizers": "seizures", "seizuring": "seizing", "siezing": "seizing",
    "anafalaxis": "anaphylaxis", "anaphalaxis": "anaphylaxis", "anafylaxis": "anaphylaxis", "anaphylaxsis": "anaphylaxis",
    "anaphalactic": "anaphylactic", "anaphylatic": "anaphylactic", "anafalactic": "anaphylactic",
    "alergic": "allergic", "swolen": "swollen", "sweling": "swelling", "throt": "throat", "thoat": "throat", "tounge": "tongue",
    "bleading": "bleeding", "bleding": "bleeding", "bledding": "bleeding", "alot": "a lot",
    "passd": "passed", "pased": "passed", "past out": "passed out",
    "colapsed": "collapsed", "collasped": "collapsed", "colasped": "collapsed", "colapse": "collapse",
    "sucidal": "suicidal", "suicidle": "suicidal", "suicidel": "suicidal", "sucidle": "suicidal", "suisidal": "suicidal",
    "suiside": "suicide", "sucide": "suicide", "suside": "suicide", "suecide": "suicide", "suicde": "suicide",
    "myslef": "myself", "myslf": "myself", "mysef": "myself", "stoped": "stopped",
    "od'd": "overdosed", "oded": "overdosed", "od'ed": "overdosed", "over dose": "overdose", "over dosed": "overdosed",
    "to many": "too many",
}

# Household chemicals a person might swallow (English rules), including "something from under the sink".
HOUSEHOLD_CHEMICALS = (
    r"bleach|clorox|lysol|pine.?sol|windex|drano|draino|comet|ajax|febreze|ammonia|lye|disinfectant|sanitizer|antifreeze|coolant"
    r"|(?:drain|oven|toilet|toilet bowl|glass|floor|bathroom|kitchen|tile|carpet|grill|window|all.?purpose|household|bowl) cleaners?"
    r"|cleaning (?:stuff|products?|supplies|spray|solution|liquid|fluid|chemicals?)|(?:laundry|dish|dishwasher|tide) (?:pods?|soap|detergent|tablets?|liquid)|detergent"
    r"|windshield (?:washer )?fluid|washer fluid|gasoline|kerosene|lamp oil|lighter fluid|paint thinner|turpentine|acetone|nail polish remover|rubbing alcohol|isopropyl"
    r"|hydrogen peroxide|pesticide|insecticide|bug (?:spray|killer)|roach (?:spray|killer|bait)|weed killer|roundup|herbicide|rat poison|mouse poison|rodent poison"
    r"|pool (?:chemicals?|shock|chlorine)|chlorine|battery acid|caustic|mothballs?|(?:something|stuff|a bottle|a cup|liquid|chemicals?)(?: \w+){0,2} (?:from |out of )?under (?:the|our|my|her|his) "
    r"(?:kitchen |bathroom )?sink|chemicals?"
)

# Fever words in every offered language, for the child fever rules.
FEVER_WORDS = "发烧|發燒|发热|發熱|高烧|高燒|बुखार|ज्वर|بخار|حرارة|حمى|سخونة|জ্বর|жар|температур|熱|発熱|열이|열나|고열|sốt"

# Pregnancy warning signs in the patient's own words (the form's pregnant flag is often the only English).
PREGNANCY_WARNING = (
    "sangrando|sangrado|sangro|manchando|baja sangre|sale sangre|se rompio la fuente|rompi la fuente|se rompio la bolsa|no se mueve|se mueve poco|veo borroso|vision borrosa|dolor de cabeza muy fuerte"
    "|perdu les eaux|bouge plus|bouge moins|vision floue|bolsa estourou|bolsa rompeu|nao mexe|mexendo pouco|visao turva"
    "|出血|流血|见红|見紅|破水|羊水破|胎动很少|胎动少|胎動|看不清|模糊"
    "|chảy máu|ra máu|vỡ ối|ít đạp|không đạp|nhìn mờ|đau đầu dữ dội"
    "|نزيف|نازل دم|ينزل دم|بينزل دم|نزل دم|نزلت الميه|نزلت المية|نزل الماء|مش بيتحرك|ما يتحرك|ما بيتحرك|زغلله|زغللة|صداع شديد"
    "|खून आ रहा|खून आ रही|खून निकल|खून बह|रक्तस्राव|पानी टूट|पानी निकल|कम हिल|हिल नहीं|धुंधला|तेज सिरदर्द|ब्लीडिंग"
    "|dinudugo|dumudugo|nagdudugo|may dugo|panubigan|hindi gumagalaw|hindi masyadong gumagalaw|malabo ang paningin|sobrang sakit ng ulo"
    "|피가|출혈|양수|태동|흐려|흐릿|머리가 너무 아프"
    "|кровотечени|кровит|идет кровь|пошла кровь|кровян|отошли воды|не шевел|мушки|сильно болит голова"
)

# A young child not peeing, and very sleepy, in the app's other languages.
CHILD_NO_PEE = ("没尿|没有尿|沒尿|不尿|không đi tiểu|ما عمل بيبي|ما عملت بيبي|ما بال|ما بالت|पेशाब नहीं|hindi umiihi|di umiihi"
    "|소변을 안|소변을 못|소변 안|не писал|не писала|не мочился")
CHILD_SLEEPY = "昏睡|嗜睡|昏昏欲睡|没精神|沒精神|lừ đừ|li bì|نايم|نايمه|خامل|سست|सुस्त|antukin|matamlay|처져|늘어져|вял|сонлив"

# High-frequency words of the app's other languages, typed in Latin letters, that are not English
# words, plus Arabizi digit-letters ("3andi", "2ader") but not "2nd", "8am" or "10mg".
FOREIGN_WORDS = (
    r"\b(?:el|la|los|las|y|que|del|por|para|muy|tengo|tiene|estoy|esta|duele|dolor|quiero|puedo|puede|mucho|mucha|sangre|pecho|se|le|"
    r"nao|estou|meu|minha|muito|dor|peito|sangue|com|ele|ela|je|j'ai|pas|est|et|tres|ne|il|elle|suis|mal|poitrine|ca|"
    r"ho|non|sono|mio|di|molto|petto|ich|habe|nicht|und|mein|meine|ist|sehr|soll|keine|kann|mir|tut|weh|brust|luft|"
    r"ang|ng|ko|sa|yung|po|hindi|masakit|ayaw|ayoko|ako|siya|sya|nang|mga|lang|sobrang|dugo|dibdib|"
    r"saya|aku|tidak|nggak|gak|sakit|yang|sekali|banget|nyeri|dada|napas|nafas|darah|terus|sesak|"
    r"hai|hain|nahi|nahin|nhi|raha|rahi|rahe|mera|meri|mujhe|bahut|aur|ka|ki|ke|gaya|gayi|dard|saans|khoon|seene|chahta|"
    r"ana|fi|msh|mesh|mish|bdi|wo|ni|bu|hao|teng|xiong|kou|xue|toi|bi|khong|qua|duoc|tho|nguc|mau|chay|roi|"
    r"menya|bolit|mogu|khochu|ochen|ona|ga|desu|masu|itai|nai|dekinai|mune|neomu|apayo|eopseoyo|sipeoyo|"
    r"mikone|nemitoonam|kheili|sinam|shode|ami|amar|khub|betha|hocche|parchi|buke|cok|bir|ve|nie|mnie|jest|sie|bardzo|boli|chce)\b"
    r"|\b(?!\d+(?:st|nd|rd|th|am|pm|mg|mcg|ml|kg|kgs|g|lbs?|oz|cm|mm|ft|in|hrs?|mins?|secs?|days?|wks?|weeks?|months?|yrs?|years?|yo|x|f|c|bpm|units?)\b)[a-z]*[2-9][a-z]+\b"
)

# Languages written in Latin letters: matched on accent-free, misspelling-folded text with word edges.
LATIN_CODES = {"es", "fr", "pt", "tl", "de", "it", "tr", "pl", "id",
               "hi_latn", "ar_latn", "zh_latn", "ru_latn", "ja_latn", "ko_latn", "fa_latn", "bn_latn"}

# Red flags by language. Keys: resus (ESI 1), stroke (ESI 1), and the ESI 2 groups.
LEXICONS: dict[str, dict[str, str]] = {
    "es": {"resus": r"no respira|dejo de respirar|inconsciente|no responde|no reacciona|no despierta|perdio el conocimiento|se esta ahogando|labios morados",
           "stroke": r"derrame(?: cerebral)?|ataque cerebral|embolia|accidente cerebrovascular|(?:cara|boca) (?:caida|torcida|chueca|ladeada)|habla (?:arrastrada|enredada)|arrastra las palabras|(?:debil|dormid|adormecid|entumecid)\w* (?:en |de )?un lado",
           "chest": r"dolor (?:\w+ ){0,2}(?:de|en el|en mi|del) pecho|me duele (?:mucho |el |la )*pecho|pecho me duele|(?:presion|opresion) en el pecho|dolor toracico|infarto|ataque al corazon",
           "breath": r"no (?:puedo|puede) respirar|(?:me|le) cuesta respirar|(?:me|le) falta el aire|falta de aire|me ahogo|se ahoga|dificultad para respirar|no me entra (?:el )?aire",
           "bleed": r"sangra mucho|sangrando mucho|no (?:para|deja) de sangrar|sangrado (?:abundante|fuerte|que no para)|hemorragia|mucha sangre|vomit\w* sangre|tos con sangre",
           "crisis": r"suicid\w*|(?:me )?quiero morir(?:me)?|(?:me )?quiero matar(?:me)?|quitarme la vida|matarme|no quiero (?:seguir )?vivir|acabar con mi vida|hacerme dano",
           "faint": r"me desmaye|se desmayo|desmay\w*", "seizure": r"convulsi\w*|ataque epileptico",
           "allergy": r"se me (?:esta )?hinch\w* (?:la garganta|la lengua|los labios|la cara)|(?:garganta|lengua) hinchada|labios hinchados|reaccion alergica",
           "pregnancy": r"embarazada.{0,60}sangr\w*|sangr\w*.{0,60}embarazada", "overdose": r"sobredosis|me tome (?:todas las|un frasco|muchas) (?:de )?pastillas"},
    "fr": {"resus": r"ne respire (?:plus|pas)|inconscient\w*|ne repond (?:plus|pas)|ne se reveille pas|perdu connaissance",
           "stroke": r"avc|accident vasculaire|visage (?:paralyse|tombant|de travers|deforme)|bouche de travers|(?:faiblesse|engourdi\w*|paralys\w*) (?:d'un|du) cote",
           "chest": r"douleur (?:\w+ )?(?:a|dans|sur) la poitrine|douleur thoracique|mal (?:a|dans) la poitrine|(?:serrement|oppression|pression) (?:dans|sur|a) la poitrine|crise cardiaque|infarctus",
           "breath": r"n'arrive (?:pas|plus) a respirer|ne (?:peux|peut) (?:pas|plus) respirer|du mal a respirer|difficulte a respirer|essouffl\w*|j'etouffe|manque d'air",
           "bleed": r"saigne (?:beaucoup|enormement|abondamment)|saignement (?:abondant|important)|(?:n'arrete|ne s'arrete) pas de saigner|hemorragie|beaucoup de sang",
           "crisis": r"suicid\w*|envie de mourir|veux mourir|me tuer|en finir avec (?:la|ma) vie|mettre fin a (?:mes jours|ma vie)|me faire du mal",
           "faint": r"evanoui\w*"},
    "pt": {"resus": r"nao (?:esta )?respira\w*|parou de respirar|inconsciente|nao responde|nao acorda|desacordad\w*",
           "stroke": r"avc|derrame|rosto (?:caido|torto)|boca torta|fala enrolada|(?:fraqueza|dormencia|formigamento) (?:de|em|no) (?:um|o) lado",
           "chest": r"dor (?:\w+ ){0,2}no peito|dor toracica|(?:aperto|pressao) no peito|peito doi|ataque cardiaco|infarto",
           "breath": r"nao (?:consigo|consegue) respirar|falta de ar|dificuldade (?:para|de|em) respirar|sufocando|sem ar",
           "bleed": r"sangra(?:ndo)? muito|sangramento (?:forte|intenso)|nao para de sangrar|hemorragia|muito sangue",
           "crisis": r"suicid\w*|quero morrer|me matar|tirar (?:a )?minha (?:propria )?vida|acabar com a minha vida|nao quero (?:mais )?viver",
           "faint": r"desmai\w*"},
    "tl": {"resus": r"hindi (?:na )?humihinga|walang malay|nawalan ng malay|hindi (?:na )?gumigising",
           "stroke": r"na-?stroke|istrok|(?:tabingi|ngiwi) ang (?:mukha|bibig)|manhid ang (?:isang|kalahating) (?:bahagi|parte)",
           "chest": r"masakit (?:ang )?(?:aking |ang )?dibdib|sakit sa dibdib|kirot sa dibdib|paninikip ng dibdib|naninikip ang dibdib|atake sa puso",
           "breath": r"hindi (?:ako |siya )?makahinga|hirap (?:akong |siyang )?huminga|nahihirapan(?:g)? (?:akong |siyang )?huminga|kinakapos (?:ng|sa) hininga|hinihingal",
           "bleed": r"dumudugo nang (?:husto|marami|malakas)|malakas na pagdurugo|(?:hindi|ayaw) tumigil ang (?:pagdurugo|dugo)|(?:ang daming|maraming) dugo",
           "crisis": r"magpakamatay|nagpapakamatay|gusto (?:ko nang|kong) mamatay|(?:ayoko|ayaw ko) nang mabuhay|(?:tapusin|wakasan) ang buhay ko|saktan ang sarili",
           "faint": r"nahimatay"},
    "de": {"resus": r"atmet nicht(?: mehr)?|bewusstlos\w*|reagiert nicht|wacht nicht (?:mehr )?auf",
           "stroke": r"schlaganfall|gesicht (?:hangt|ist schief|verzogen)|mundwinkel hangt|(?:lallende|verwaschene|undeutliche) sprache|(?:eine|einer) seite (?:taub|schwach|gelahmt)",
           "chest": r"brustschmerz\w*|schmerzen in der brust|(?:druck|enge|engegefuhl) (?:in|auf) der brust|brust tut (?:sehr )?weh|herzinfarkt",
           "breath": r"kann nicht (?:mehr )?atmen|keine luft|(?:kriege|bekomme) (?:kaum|keine) luft|atemnot|schwer zu atmen",
           "bleed": r"blutet (?:sehr )?(?:stark|viel)|starke blutung|(?:hort|horen) nicht auf zu bluten|viel blut",
           "crisis": r"suizid\w*|selbstmord\w*|mich umbringen|will sterben|mochte sterben|nicht mehr leben|mir das leben nehmen|mich selbst verletzen",
           "faint": r"ohnmacht\w*|kollabiert|zusammengebrochen"},
    "it": {"resus": r"non respira|priv[oa] di sensi|incoscient\w*|non risponde|non si sveglia",
           "stroke": r"ictus|faccia (?:storta|cadente)|bocca storta|(?:debolezza|formicolio|intorpidimento) (?:a|da|su) un lato",
           "chest": r"dolore (?:\w+ )?al petto|dolore toracico|mi fa male il petto|(?:oppressione|peso|pressione) (?:al|sul) petto|infarto",
           "breath": r"non riesc[oe] a respirare|non respiro|fatica a respirare|difficolta a respirare|mi manca l'aria|fiato corto|soffoco",
           "bleed": r"sanguina (?:molto|tanto|tantissimo)|emorragia|(?:il )?sangue non si ferma|non smette di sanguinare|tanto sangue",
           "crisis": r"suicid\w*|voglio morire|uccidermi|ammazzarmi|togliermi la vita|farla finita|non voglio piu vivere|farmi del male",
           "faint": r"svenut\w*|svenimento|perso i sensi"},
    "tr": {"resus": r"nefes almiyor|bilinci kapali|bilincini kaybet\w*|tepki vermiyor|uyanmiyor",
           "stroke": r"inme gecir\w*|felc|(?:yuzu|yuzum|agzi|agzim) kay\w*|yuz kaymasi|(?:konusmasi|konusmam) bozul\w*|(?:bir|tek) taraf\w* (?:uyus\w*|gucsuz\w*)",
           "chest": r"gogus agrisi|gogsum(?:de)? (?:\w+ )?agri\w*|gogsumde baski|kalp krizi",
           "breath": r"nefes alamiyor\w*|nefes almakta zorlan\w*|nefesim daral\w*|nefes darligi|boguluyor\w*",
           "bleed": r"kanama durmuyor|kan durmuyor|cok kaniyor|siddetli kanama|asiri kanama",
           "crisis": r"intihar|olmek istiyorum|kendimi oldur\w*|yasamak istemiyorum|canima kiy\w*|kendime zarar",
           "faint": r"bayil\w*"},
    "pl": {"resus": r"nie oddycha|nieprzytomn\w*|stracil\w* przytomnosc|nie reaguje|nie budzi sie",
           "stroke": r"udar\w*|opadnie\w* kacik\w*|twarz (?:opadla|krzywa|wykrzywiona)|belkot\w*|niewyrazn\w* mow\w*|(?:dretwienie|oslabienie|niedowlad) (?:jednej strony|po jednej stronie)",
           "chest": r"bol w klatce|boli mnie (?:w )?klatk\w*|bol w piersi|ucisk w klatce|zawal\w*",
           "breath": r"nie (?:moge|moze) oddychac|nie moge zlapac tchu|dus(?:ze|i) sie|dusznosc|brakuje mi powietrza|(?:trudnosci z oddychaniem|ciezko mi oddychac)",
           "bleed": r"(?:mocno|bardzo|duzo) krwawi\w*|krwawi\w* (?:mocno|bardzo|duzo)|silne krwawienie|krwawienie nie ustaje|krew nie przestaje|krwotok\w*|duzo krwi",
           "crisis": r"samoboj\w*|chce umrzec|zabic sie|odebrac sobie zycie|nie chce zyc|skonczyc ze soba|zrobic sobie krzywde",
           "faint": r"zemdlal\w*|omdleni\w*"},
    "id": {"resus": r"tidak berna[pf]as|tidak sadarkan diri|hilang kesadaran|tidak merespons",
           "stroke": r"(?:wajah|mulut) (?:mencong|turun|miring|perot)|bicara(?:nya)? pelo|(?:lemah|mati rasa|lumpuh|kesemutan) (?:sebelah|satu sisi)",
           "chest": r"nyeri dada|sakit dada|dada (?:saya |terasa |sangat )?(?:sakit|nyeri|sesak|berat|tertekan)|serangan jantung",
           "breath": r"tidak bisa berna[pf]as|sesak na[pf]as|susah (?:berna[pf]as|na[pf]as)|sulit berna[pf]as|(?:nggak|gak|ga) bisa na[pf]as",
           "bleed": r"pe(?:n)?darahan (?:hebat|parah|banyak)|perdarahan (?:hebat|parah|banyak)|darah(?:nya)? tidak (?:mau )?berhenti|berdarah (?:banyak|terus|parah|hebat)|banyak darah",
           "crisis": r"bunuh diri|ingin mati|mau mati|pengen mati|mengakhiri hidup|tidak ingin hidup|melukai diri",
           "faint": r"pingsan"},
    "vi": {"resus": r"ngừng thở|ngung tho|tắt thở|bất tỉnh|bat tinh|hôn mê|hon me",
           "stroke": r"đột quỵ|dot quy|tai biến|tai bien|méo miệng|meo mieng|(?:liệt|yếu|tê) nửa người|(?:liet|yeu|te) nua nguoi",
           "chest": r"đau ngực|dau nguc|tức ngực|tuc nguc|nhồi máu cơ tim|đau tim",
           "breath": r"khó thở|kho tho|không thở được|khong tho duoc|ngạt thở|ngat tho|thở không nổi",
           "bleed": r"chảy máu (?:nhiều|không ngừng|không cầm|liên tục)|chay mau (?:nhieu|khong ngung|khong cam)|mất máu nhiều|mat mau nhieu|băng huyết",
           "crisis": r"tự tử|tự sát|tu sat|muốn chết|muon chet|không muốn sống|khong muon song|tự làm hại",
           "faint": r"ngất|ngat xiu|xỉu"},
    # "没有呼吸困难" is "no trouble breathing", not "not breathing"
    "zh": {"resus": r"(?:没有|沒有|不|没|沒)呼吸(?!困难|困難|问题|問題|急促|不畅|不暢|短促|费力|費力|道)|停止呼吸|昏迷|失去知觉|失去知覺|不省人事|叫不醒|没反应|沒反應",
           "stroke": r"中风|中風|脑卒中|腦卒中|脑梗|腦梗|口歪|嘴歪|脸歪|臉歪|口齿不清|口齒不清|说话不清|說話不清|半身(?:无力|無力|麻木|不遂)|一[侧側边邊](?:手脚|手腳)?(?:无力|無力|麻木)",
           "chest": r"胸口(?:很|好|非常|特别|特別)?(?:痛|疼)|胸(?:痛|疼)|心口(?:痛|疼)|胸闷|胸悶|胸部(?:疼痛|压迫|壓迫)|心脏病发|心臟病發",
           "breath": r"喘不过气|喘不過氣|呼吸困难|呼吸困難|不能呼吸|无法呼吸|無法呼吸|透不过气|透不過氣|上不来气|上不來氣|喘不上气|喘不上氣|窒息",
           "bleed": r"大出血|流血不止|血流不止|止不住血|血止不住|出血(?:很|好|非常)?多|一直流血|流很多血",
           "crisis": r"自杀|自殺|想死|不想活|[结結]束(?:我的)?生命|轻生|輕生|伤害自己|傷害自己",
           "faint": r"晕倒|暈倒|昏倒|晕过去|暈過去|晕厥|暈厥"},
    "ja": {"resus": r"息をしていない|呼吸をしていない|意識がない|意識不明|反応がない|目を覚まさない",
           "stroke": r"脳卒中|脳梗塞|脳出血|顔(?:の片側)?が(?:垂れ|ゆがん|歪ん|下が)|ろれつが回らない|呂律が回らない|(?:片側|半身)(?:の|が)?(?:麻痺|まひ|しびれ|痺れ)",
           "chest": r"胸が(?:痛|苦し|締め付け)|胸の痛み|胸痛|心臓発作",
           "breath": r"息ができない|息が(?:苦しい|できない)|呼吸が(?:苦しい|できない)|呼吸困難|息苦しい",
           "bleed": r"血が止まらない|出血が(?:ひどい|止まらない|多い)|大量出血|大量の血",
           "crisis": r"自殺|死にたい|消えたい|生きていたくない|命を絶|自分を傷つけ",
           "faint": r"気を失|失神"},
    "ko": {"resus": r"숨을 안 ?쉬|숨을 쉬지 않|숨이 멈|의식(?:이|을)? ?(?:없|잃)|반응이 없|깨어나지 않",
           "stroke": r"뇌졸중|중풍|뇌경색|뇌출혈|얼굴(?:이)? ?(?:한쪽으로|한쪽이)? ?(?:처지|처져|처졌|비뚤|마비)|입이 (?:돌아|비뚤)|(?:말|발음)이 어눌|한쪽 (?:팔|다리|몸)(?:이|에)? ?(?:힘이 없|마비|감각이 없)|반신 ?마비",
           "chest": r"가슴(?:이)? ?(?:너무 |많이 |심하게 )?(?:아파|아프|답답|조여)|가슴 통증|흉통|심장마비",
           "breath": r"숨(?:을|이)? ?(?:쉴 수 없|못 ?쉬|쉬기 (?:힘들|어려)|차|막혀|가빠)|호흡 ?곤란",
           "bleed": r"피가 (?:많이 나|멈추지 않|안 멈|계속 나|너무 많이)|출혈이 (?:심|많)|(?:과다|대량) ?출혈",
           "crisis": r"자살|죽고 ?싶|살고 ?싶지 않|목숨을 끊|자해", "faint": r"기절|실신|쓰러졌"},
    "ar": {"resus": r"لا (?:يتنفس|تتنفس)|توقف عن التنفس|(?:فاقد|فاقدة|فقد|فقدان|غائب عن) الوعي|لا (?:يستجيب|تستجيب)",
           "stroke": r"(?:جلطة|سكتة) دماغية|جلطة في الدماغ|(?:تدلي|ارتخاء) (?:في )?الوجه|اعوجاج (?:في )?الفم|ثقل في (?:الكلام|اللسان)|(?:خدر|ضعف) في (?:جانب|نصف)|شلل نصفي",
           "chest": r"ألم (?:شديد |قوي )?في (?:ال)?صدر|صدري يؤلمني|وجع (?:في )?(?:ال)?صدر|ضيق في الصدر|ضغط على الصدر|(?:نوبة|أزمة) قلبية",
           "breath": r"لا (?:أستطيع|أقدر|يمكنني|يستطيع|تستطيع) (?:أن )?(?:أتنفس|التنفس)|صعوبة في التنفس|ضيق (?:في )?(?:ال)?(?:تنفس|نفس)|(?:ما أقدر|مش قادر|مو قادر) أتنفس|اختناق|أختنق",
           "bleed": r"نزيف (?:حاد|شديد|قوي|كثير|لا يتوقف)|الدم لا يتوقف|ينزف (?:بشدة|كثيرا|بغزارة)|دم كثير",
           "crisis": r"انتحار|انتحر|أريد (?:أن أموت|الموت)|(?:أبغى|أبي|بدي) أموت|أقتل نفسي|أنهي حياتي|لا أريد أن أعيش|أؤذي نفسي|إيذاء نفسي",
           "faint": r"أغمي (?:عليه|علي|عليها)|مغمى عليه|إغماء"},
    "fa": {"resus": r"نفس نمی ?کشد|بیهوش|از هوش رفت|هوشیار نیست",
           "stroke": r"سکته مغزی|افتادگی صورت|(?:صورتم|صورتش|دهانم|دهانش) کج|کج شدن (?:صورت|دهان)|(?:بی ?حسی|ضعف|فلج) (?:یک|یه) طرف",
           "chest": r"درد (?:شدید )?(?:در )?(?:قفسه )?سینه|سینه ?ام درد|فشار (?:روی|در) سینه|حمله قلبی",
           "breath": r"نمی ?(?:توانم|تونم) نفس بکشم|نفسم بالا نمی ?(?:آید|اد)|نفسم بالا نمیاد|تنگی نفس|نفس تنگی|به سختی نفس|خفه می ?شوم",
           "bleed": r"خون ?ریزی (?:شدید|زیاد)|خون بند نمی ?(?:آید|اد)|خون بند نمیاد|خون زیادی",
           "crisis": r"خودکشی|می ?(?:خواهم|خوام) بمیرم|خودم ?(?:را|رو|و) بکشم|نمی ?(?:خواهم|خوام) زنده|به خودم آسیب",
           "faint": r"غش کرد|از حال رفت"},
    "ur": {"resus": r"سانس نہیں لے (?:رہا|رہی)|سانس بند|بے ?ہوش|ہوش میں نہیں",
           "stroke": r"فالج|اسٹروک|سٹروک|چہرہ (?:ٹیڑھا|لٹک)|منہ ٹیڑھا|زبان لڑکھڑا|ایک طرف (?:کمزوری|سن)",
           "chest": r"سینے میں (?:شدید |بہت |تیز )?درد|سینے (?:میں )?(?:دباؤ|جکڑن)|چھاتی میں (?:شدید |بہت )?درد|دل کا دورہ",
           "breath": r"سانس (?:لینے میں )?(?:بہت )?(?:تکلیف|دقت|مشکل)|سانس نہیں (?:لے سکتا|لے سکتی|آ رہی|آرہی)|سانس پھول|دم گھٹ",
           "bleed": r"بہت (?:زیادہ )?خون (?:بہہ|نکل)|خون (?:نہیں )?رک (?:نہیں|ہی نہیں)|خون بند نہیں",
           "crisis": r"خودکشی|مرنا چاہتا|مرنا چاہتی|جینا نہیں چاہت|اپنی جان لے|خود کو (?:مار|نقصان)",
           "faint": r"غش"},
    "hi": {"resus": r"सांस नहीं ले (?:रहा|रही)|सांस बंद|बेहोश|होश (?:में )?नहीं",
           "stroke": r"लकवा|स्ट्रोक|चेहरा (?:टेढ़ा|लटक)|मुंह टेढ़ा|(?:जबान|जुबान) लड़खड़ा|एक तरफ (?:कमज़ोरी|कमजोरी|सुन्न)|आधा शरीर (?:सुन्न|कमजोर)",
           "chest": r"(?:सीने|छाती) में (?:बहुत |तेज़ |तेज |भयंकर |जोर से )?(?:दर्द|जकड़न|दबाव)|सीना दर्द|दिल का दौरा",
           "breath": r"सांस (?:लेने में )?(?:बहुत )?(?:तकलीफ|दिक्कत|परेशानी|मुश्किल)|सांस नहीं (?:ले पा|आ रही|आ रहा)|दम घुट|सांस फूल",
           "bleed": r"बहुत (?:ज़्यादा |ज्यादा )?खून (?:बह|निकल)|खून (?:नहीं )?रुक (?:नहीं|ही नहीं)|खून बंद नहीं",
           "crisis": r"आत्महत्या|खुदकुशी|मरना चाहत|जीना नहीं चाहत|अपनी जान (?:ले|देना)|खुद को (?:मार|नुकसान)",
           "faint": r"बेहोश हो"},
    "bn": {"resus": r"(?:নিঃ)?শ্বাস নিচ্ছে না|অজ্ঞান|জ্ঞান নেই|জ্ঞান হারি",
           "stroke": r"স্ট্রোক|মুখ (?:বেঁকে|বাঁকা)|কথা জড়িয়ে|এক পাশ (?:অবশ|দুর্বল)|প্যারালাইসিস|পক্ষাঘাত",
           "chest": r"বুকে (?:খুব |প্রচণ্ড |তীব্র )?(?:ব্যথা|চাপ)|বুক ব্যথা|হার্ট অ্যাটাক",
           "breath": r"(?:নিঃ)?শ্বাস নিতে (?:কষ্ট|পারছি না|পারছিনা|পারছে না)|শ্বাসকষ্ট|দম বন্ধ",
           "bleed": r"রক্ত (?:বন্ধ হচ্ছে না|থামছে না)|প্রচুর রক্ত|অনেক রক্ত (?:পড়ছে|ঝরছে|যাচ্ছে)|রক্তক্ষরণ",
           "crisis": r"আত্মহত্যা|মরে যেতে চাই|মরতে চাই|বাঁচতে চাই না|নিজেকে (?:মেরে|শেষ)|নিজের ক্ষতি",
           "faint": r"অজ্ঞান হয়ে"},
    "ru": {"resus": r"не дышит|перестала? дышать|без сознания|потерял(?:а)? сознание|не приходит в себя|не реагирует",
           "stroke": r"инсульт|лицо перекос\w*|перекосило лицо|онемел(?:а|о)? (?:одна сторона|половина)|слабость в (?:одной|левой|правой) (?:руке|ноге|стороне)|невнятная речь|заплетается язык",
           "chest": r"боль в груди|болит (?:в )?груд\w*|груд\w* болит|давит (?:в )?груди|сжимает грудь|жжение в груди|инфаркт|сердечный приступ",
           "breath": r"не (?:могу|может) дышать|(?:трудно|тяжело) дышать|задыха\w*|не хватает воздуха|одышка",
           "bleed": r"сильное кровотечение|кровь не останавлива\w*|не могу остановить кровь|сильно кровоточ\w*|много крови",
           "crisis": r"суицид|покончить с собой|хочу умереть|убить себя|не хочу жить|самоубийств\w*|причинить себе вред",
           "faint": r"(?:упал|упала) в обморок|обморок"},
}

# Red-team additions. Each line closes check-ins that were under-triaged with no AI key:
# filler words and other word orders ("胸口很痛", "muy fuerte"), dialect forms, romanized
# typing, special populations (pregnancy, a child who swallowed a battery, a fall on a
# blood thinner, new confusion). Never use \S, \W, \D or \B here: normalize() lowercases the pattern.
LEXICON_MORE: list[tuple[str, str, str]] = [
    # Spanish
    ("es", "chest", r"(?:presion|opresion|peso|dolor|ardor|apreton) (?:\w+ ){0,3}(?:en el|en mi|del) pecho"),
    ("es", "chest", r"(?:aprieta|oprime|aplasta|presiona|quema|arde)\w* (?:\w+ ){0,2}(?:el |mi )?pecho|pecho (?:\w+ ){0,3}(?:aprieta|oprime|duele|dolor|presion)"),
    ("es", "breath", r"me (?:estoy )?ahog\w*|se (?:esta )?ahog\w*|no me (?:pasa|entra|llega) (?:el )?aire|me falta (?:el )?aire"),
    ("es", "bleed", r"sangr\w* (?:muchisimo|demasiado|bastante|sin parar|un monton)"),
    ("es", "bleed", r"no (?:para|deja|dejaba|paraba) de (?:sangrar|salir sangre|echar sangre)|sangre (?:\w+ ){0,2}(?:sin parar|no para)"),
    ("es", "crisis", r"acabar con todo|ya no (?:aguanto|puedo) (?:mas )?(?:vivir|con la vida)|no vale la pena vivir|me quiero (?:morir|matar)"),
    ("es", "crisis", r"quitar(?:me)? la vida|(?:pienso|pensando) en (?:matarme|suicidarme|morirme)"),
    ("es", "stroke", r"se (?:le|me) (?:cayo|cae|esta cayendo|ladeo|torcio) (?:la cara|la boca)|(?:cara|boca) (?:\w+ ){0,2}(?:caida|torcida|chueca|ladeada) (?:de|hacia) un lado"
                     r"|de repente (?:\w+ ){0,3}no (?:puede|puedo) mover (?:el|la|su|mi) (?:brazo|pierna|mano|lado)"),
    ("es", "overdose", r"se (?:trago|comio) (?:una |un |unas |unos |dos |varios |varias )?(?:pilas?|baterias?|imanes|iman|pila de boton)"),
    ("es", "pregnancy", r"(?:embarazada|embarazo|\d+ semanas).{0,60}(?:se me rompio la fuente|rompi (?:la )?fuente|se rompio la (?:fuente|bolsa)|no se mueve|ya no se mueve|veo borroso|vision borrosa|dolor de cabeza muy fuerte)"
                        r"|(?:se me rompio la fuente|rompi (?:la )?fuente|se rompio la (?:fuente|bolsa)|el bebe no se mueve|veo borroso).{0,60}(?:embarazada|embarazo|\d+ semanas)"),
    ("es", "head", r"(?:se (?:cayo|pego|golpeo)|me (?:cai|pegue|golpee)).{0,40}cabeza.{0,60}(?:anticoagulante\w*|confundid\w*|vomit\w*|desmay\w*)"),
    ("es", "altered", r"(?:confundid[oa]|desorientad[oa]) de repente|de repente (?:\w+ ){0,2}(?:confundid[oa]|desorientad[oa])|no reconoce a nadie"),
    # Chinese (Simplified and Traditional)
    ("zh", "chest", r"心[脏臟].{0,4}(?:痛|疼|闷|悶)|胸.{0,4}(?:痛|疼|闷|悶|压|壓)|chest.{0,3}(?:痛|疼)"),
    ("zh", "breath", r"呼吸.{0,2}(?:困难|困難)|吸不(?:到|上|进|進)(?:气|氣)|呼吸不(?:了|过来|過來)"),
    ("zh", "breath", r"breathe?(?:ing)? ?不(?:了|过来|過來|到)"),   # code-switching: "我觉得breathe不了"
    ("zh", "bleed", r"血.{0,4}(?:停不下来|停不下來|止不住|不停|流个不停|流個不停)|一直(?:在)?(?:流|出)血|流(?:了)?(?:好多|很多)血"),
    ("zh", "faint", r"昏过去|昏過去|晕了过去|暈了過去"),
    ("zh", "resus", r"叫不(?:太)?醒|没(?:有)?反应|沒(?:有)?反應"),
    ("zh", "crisis", r"活着没意思|活著沒意思|想结束(?:这一切|一切|生命)|想結束(?:這一切|一切|生命)|自尽|自盡"),
    ("zh", "stroke", r"(?:左边|右边|一边|半边|左侧|右侧|左邊|右邊|一邊|半邊|左側|右側)(?:的)?(?:手脚|手腳|手|脚|腳|身体|身體|身子).{0,4}(?:没力|沒力|无力|無力|麻|不能动|動不了|动不了)"),
    ("zh", "overdose", r"吞(?:了|下)?.{0,6}(?:电池|電池|磁铁|磁鐵|纽扣|紐扣)"),
    ("zh", "pregnancy", r"(?:怀孕|懷孕).{0,20}(?:出血|流血|见红|見紅|破水|胎动|胎動|看不清|视力模糊)|(?:出血|流血|见红|見紅|破水).{0,20}(?:怀孕|懷孕)"),
    ("zh", "head", r"(?:摔|撞|磕).{0,6}(?:头|頭).{0,20}(?:抗凝|华法林|華法林|吐|昏|糊涂|糊塗)"),
    ("zh", "altered", r"突然(?:糊涂|糊塗|神志不清|意识模糊|意識模糊)|不(?:认识|認識)人|神志不清"),
    # Hindi
    ("hi", "chest", r"(?:सीने|छाती|सीना) (?:में )?(?:[^ ]+ ){0,3}(?:दर्द|जकड़न|दबाव|भारीपन)"),
    ("hi", "bleed", r"खून (?:[^ ]+ ){0,2}(?:बह रहा|बह रही|रुक नहीं|बंद नहीं)"),
    ("hi", "bleed", r"(?:बहुत|ज्यादा) (?:[^ ]+ )?ब्लीडिंग|ब्लीडिंग (?:[^ ]+ ){0,2}(?:रुक नहीं|बंद नहीं)"),
    ("hi", "crisis", r"जीने का (?:मन|दिल) नहीं|मर जाना चाहत|खुद को खत्म|अपने आप को (?:मार|खत्म)"),
    ("hi", "stroke", r"(?:चेहरा|मुंह|मुँह) (?:[^ ]+ ){0,3}(?:टेढ़ा|लटक|तिरछा)"),
    ("hi", "stroke", r"एक तरफ (?:का |की |के )?(?:हाथ|पैर|हिस्सा|शरीर).{0,24}(?:काम नहीं|सुन्न|कमजोर|नहीं हिल|उठ नहीं)"),
    ("hi", "resus", r"(?:उठ|जाग) नहीं (?:रहा|रही|रहे).{0,30}(?:बोल नहीं|जवाब नहीं)|(?:बोल नहीं|जवाब नहीं).{0,30}(?:उठ|जाग) नहीं"),
    ("hi", "pregnancy", r"(?:गर्भवती|प्रेग्नेंट|गर्भ).{0,40}(?:खून|रक्तस्राव|पानी)|(?:खून|रक्तस्राव).{0,40}(?:गर्भवती|प्रेग्नेंट)"),
    ("hi", "overdose", r"बैटरी निगल|निगल (?:[^ ]+ ){0,2}बैटरी|चुंबक निगल"),
    ("hi", "altered", r"भ्रमित|किसी को पहचान नहीं|पहचान नहीं (?:रहे|रही|रहा|पा)"),
    ("hi", "head", r"सिर (?:पर|में) (?:[^ ]+ ){0,2}चोट.{0,60}(?:खून पतला|ब्लड थिनर)"),
    # Arabic (MSA and dialects)
    ("ar", "chest", r"صدري (?:بي|ي|عم ي|عم بي)?(?:وجعني|وجع|ؤلمني)|(?:ألم|وجع) (?:[^ ]+ ){0,2}(?:في )?(?:ال)?صدر"),
    ("ar", "chest", r"(?:وجع|الم) (?:[^ ]+ ){0,2}(?:في |ب)(?:ال)?صدر|صدري (?:[^ ]+ )?(?:واجعني|بيوجعني|يوجعني|يعورني|بيعورني)"),
    ("ar", "breath", r"نفسي (?:مقطوع|مكتوم|ضايق|ضيق)|(?:ما|مش|مو) (?:أقدر|بقدر|قادر) (?:أتنفس|اتنفس|آخذ نفس)|ضيق (?:في )?النفس"),
    ("ar", "breath", r"مخنوق|مخنوقه|مختنق|اتخنق|(?:مش|ما|مو) (?:عارف|عارفه|قادر|قادره) (?:اخد|اخذ|اتنفس|اخود) (?:نفسي|نفس)?"),
    ("ar", "bleed", r"الدم (?:مش|ما|مو) (?:راضي|عايز|بدو|بيوقف|يوقف|واقف)|نزيف (?:[^ ]+ )?(?:كثير|كتير|جامد|قوي)"),
    ("ar", "crisis", r"(?:ما|مش|مو) (?:بدي|أبي|أبغى|عايز|عاوز) (?:أعيش|عيش)|(?:بدي|أبي|أبغى|عايز|عاوز) (?:أموت|انتحر)|(?:أقتل|بقتل) حالي"),
    ("ar", "stroke", r"(?:وجه|وجهه|وجهها|فمه|فمها|تمه|بقه) (?:[^ ]+ )?(?:مايل|معوج|ملتوي|عوج|مرتخي)"),
    ("ar", "resus", r"(?:مش|ما|مو) (?:بيفوق|يفوق|بيصحى|يصحى|بيرد|يرد|بيتنفس|يتنفس)"),
    ("ar", "pregnancy", r"حامل.{0,40}(?:نزيف|دم|نزلت المية|نزل الماء)|(?:نزيف|دم).{0,40}حامل"),
    ("ar", "overdose", r"بلع (?:[^ ]+ )?(?:بطاريه|بطارية|حجر بطاريه|مغناطيس)"),
    ("ar", "altered", r"مشوش|ملخبط|(?:ما|مش) (?:يعرف|بيعرف) (?:وين|فين) هو|(?:ما|مش) (?:يعرفني|بيعرفنا|يعرف حد)"),
    ("ar", "head", r"(?:خبط|خبطت|ضرب|ضربت|وقع|وقعت).{0,20}(?:راس|راسه|راسها|راسي).{0,60}(?:سيوله|مسيل|مميع|وارفارين)"),
    # French
    ("fr", "chest", r"(?:serre|oppresse|ecrase|compresse)\w* (?:\w+ ){0,3}(?:dans |a |sur )?la poitrine|poitrine (?:\w+ ){0,3}(?:serre|oppress\w*|ecras\w*|douleur)"),
    ("fr", "breath", r"(?:j'?arrive|il arrive|elle arrive) (?:pas|plus) a respirer|(?:je|il|elle) (?:ne )?(?:peux|peut|parviens|parvient) (?:pas|plus) (?:a )?respirer|respire (?:mal|difficilement)|je suffoque"),
    ("fr", "bleed", r"(?:n'?)?arrete (?:pas|plus) de saigner|le sang (?:\w+ )?(?:coule|gicle|ne s'?arrete pas)"),
    ("fr", "crisis", r"(?:je )?veux en finir|(?:envie|besoin) d'en finir|plus envie de vivre|me suicider|je vais me tuer"),
    ("fr", "stroke", r"(?:visage|bouche) (?:\w+ ){0,4}(?:tombe|affaisse|paralyse|de travers|devie) (?:d'un|du|sur un) cote|(?:visage|bouche) (?:est |s'est )?(?:affaiss\w*|tordu\w*)"),
    ("fr", "resus", r"(?:il|elle) (?:ne )?se reveille (?:pas|plus)|(?:il|elle) (?:ne )?repond (?:pas|plus)|arrive pas a (?:le|la) reveiller"),
    ("fr", "pregnancy", r"enceinte.{0,60}(?:saign\w*|sang|perdu les eaux|poche des eaux)|(?:saign\w*|perdu les eaux).{0,60}enceinte"),
    # Portuguese
    ("pt", "chest", r"peito (?:\w+ ){0,2}(?:doendo|doi|apertado|apertando|pesado|queimando)|(?:aperto|pressao|peso|queimacao) (?:\w+ ){0,3}no peito"),
    ("pt", "breath", r"(?:nao|n) (?:to|tou|estou|esta|ta) (?:\w+ )?(?:conseguindo|podendo) respirar|(?:to|estou|ta) sem ar"),
    ("pt", "bleed", r"o sangue (?:\w+ )?(?:nao para|nao estanca|jorrando)|sangr\w* (?:\w+ ){0,2}(?:sem parar|nao para|demais)"),
    ("pt", "crisis", r"nao aguento mais (?:viver|a vida)|nao quero mais (?:viver|estar aqui)|vontade de morrer|me suicidar|acabar com (?:tudo|a minha vida)"),
    ("pt", "stroke", r"(?:boca|rosto|cara) (?:\w+ ){0,4}(?:ficou |esta |caiu )?(?:torta|torto|caid[oa]|entortou|repuxad[oa])"),
    ("pt", "pregnancy", r"gravida.{0,60}(?:sangr\w*|sangue|bolsa (?:estourou|rompeu))|(?:sangr\w*|bolsa (?:estourou|rompeu)).{0,60}gravida"),
    # Russian
    ("ru", "chest", r"(?:жмет|давит|сжимает|ломит|печет|колет) (?:\w+ ){0,2}(?:в )?груд\w*|груд\w* (?:\w+ ){0,2}(?:жмет|давит|сжимает)"),
    ("ru", "breath", r"(?:воздуха|дыхания) не хватает|не (?:могу|может) (?:\w+ )?вдохнуть"),
    ("ru", "crisis", r"не хочу (?:больше )?жить|жить не хочу|не хочется жить|уйти из жизни"),
    ("ru", "stroke", r"(?:рот|лицо) перекоси\w*|перекоси\w* (?:рот|лицо)|речь (?:\w+ )?(?:невнятн\w*|нечетк\w*|смазан\w*)"),
    ("ru", "resus", r"не просыпа\w*|не приходит в сознание"),
    ("ru", "faint", r"отключил\w*|потерял\w* сознание"),
    ("ru", "overdose", r"проглотил\w* (?:\w+ )?(?:батарейк\w*|магнит\w*)"),
    ("ru", "altered", r"заговарива\w*|не узна(?:ет|ёт) (?:нас|меня|никого)|спутанн\w* сознани\w*"),
    ("ru", "head", r"удари\w* головой.{0,60}(?:разжижа\w*|антикоагулянт\w*|варфарин)"),
    # Japanese
    ("ja", "chest", r"胸(?:が|の)?.{0,6}(?:痛|苦し|締め付け|圧迫)"),
    ("ja", "bleed", r"(?:すごく|たくさん|大量|いっぱい|どんどん|ものすごく|かなり)(?:の)?血が|血が(?:すごく|たくさん|大量に|いっぱい|どんどん)"),
    ("ja", "crisis", r"消えてしまいたい|死んでしまいたい|生きるのがつらい"),
    ("ja", "stroke", r"(?:片側|半身|片方|左|右)の?(?:手足|手|足|腕).{0,6}(?:しびれ|痺れ|動かな|力が入らな|麻痺)"),
    ("ja", "resus", r"(?:呼んでも|起こしても|声をかけても)(?:起きない|反応しない|目を覚まさない)"),
    # Korean
    ("ko", "chest", r"가슴(?:이|을|에)? ?(?:[^ ]+ )?(?:쥐어짜|짓눌|뻐근|조이|답답)"),
    ("ko", "breath", r"숨(?:을|이)? ?쉬기(?:가)? ?(?:너무 |많이 |정말 )?(?:힘들|어려)"),
    ("ko", "bleed", r"피가 (?:[^ ]+ ){0,2}(?:많이|엄청|계속)"),
    ("ko", "crisis", r"살기 ?싫|사라지고 ?싶"),
    ("ko", "stroke", r"한쪽 (?:팔다리|팔|다리|몸)(?:에|이|가)? ?(?:힘이 (?:없|빠)|마비|감각이 없|저려|움직이지)"),
    ("ko", "resus", r"(?:깨워도|불러도) (?:안 ?일어나|반응이 없|대답이 없|안 깨)"),
    ("ko", "overdose", r"(?:건전지|배터리|자석)(?:을|를)? ?삼켰"),
    ("ko", "altered", r"정신이 (?:혼미|오락가락)|(?:사람|저|우리)(?:을|를)? ?못 ?알아"),
    ("ko", "head", r"머리(?:를|가)? ?(?:부딪|박|다쳤).{0,40}(?:혈액 ?희석|항응고|와파린)"),
    # Vietnamese (tones kept, so plain-typed forms are listed too)
    ("vi", "chest", r"ngực (?:[^ ]+ ){0,2}(?:đau|tức|nặng|thắt)|nguc (?:[^ ]+ ){0,2}(?:dau|tuc|nang|that)"),
    ("vi", "breath", r"thở không (?:được|nổi|ra)|tho khong (?:duoc|noi)|ngộp thở|ngop tho"),
    ("vi", "bleed", r"máu (?:chảy|ra) (?:nhiều|không ngừng|không cầm|mãi|liên tục)|mau (?:chay|ra) (?:nhieu|khong ngung|khong cam|mai|lien tuc)"),
    ("vi", "bleed", r"máu (?:[^ ]+ ){0,1}(?:chảy|ra) (?:không cầm|không ngừng|không dứt|mãi)|mau (?:[^ ]+ ){0,1}(?:chay|ra) (?:khong cam|khong ngung)"),
    ("vi", "crisis", r"muon tu tu|muon tu sat|muốn tự sát"),
    ("vi", "stroke", r"(?:miệng|mặt|mieng|mat) (?:[^ ]+ ){0,2}(?:méo|lệch|meo|lech)|nói (?:ngọng|đớ)|noi ngong"),
    ("vi", "resus", r"không tỉnh (?:lại|dậy)|khong tinh (?:lai|day)|gọi không tỉnh|goi khong tinh"),
    ("vi", "pregnancy", r"(?:mang thai|có thai|co thai|bầu|bau).{0,40}(?:chảy máu|ra máu|chay mau|ra mau|vỡ ối|vo oi)|(?:chảy máu|ra máu|chay mau|ra mau).{0,40}(?:mang thai|có thai|bầu)"),
    ("vi", "overdose", r"nuốt (?:phải )?(?:[^ ]+ ){0,2}(?:pin|nam châm)|nuot (?:phai )?(?:[^ ]+ ){0,2}(?:pin|nam cham)"),
    ("vi", "altered", r"lú lẫn|lu lan|lẫn lộn|không nhận ra (?:ai|người)|khong nhan ra (?:ai|nguoi)"),
    ("vi", "head", r"(?:đập|va|đụng) (?:vào )?đầu.{0,60}(?:chống đông|loãng máu)|(?:dap|va|dung) (?:vao )?dau.{0,60}(?:chong dong|loang mau)"),
    # German
    ("de", "resus", r"atmet (?:komisch|kaum|schwer|nicht richtig|seltsam)|schnappt nach luft"),
    ("de", "faint", r"zusammengesackt|zusammengebrochen|umgekippt"),
    ("de", "chest", r"tut (?:mir )?(?:die |meine )?brust (?:\w+ ){0,2}weh|brust (?:\w+ ){0,3}(?:schmerzt|druckt|eng)"),
    ("de", "breath", r"(?:bekomm\w*|krieg\w*) (?:\w+ )?(?:kaum|keine|schlecht) luft|luftnot"),
    ("de", "bleed", r"(?:blutung|blut) (?:\w+ ){0,2}(?:hort|horen) nicht (?:mehr )?auf"),
    ("de", "stroke", r"(?:redet|spricht) (?:\w+ ){0,3}(?:verwaschen|undeutlich|lallend)"),
    # Italian
    ("it", "chest", r"(?:morsa|peso|oppressione|stretta|bruciore) (?:\w+ ){0,3}(?:al|sul|nel) petto"),
    ("it", "breath", r"mi manca (?:il respiro|il fiato)|non riesco a prendere fiato|affanno"),
    ("it", "bleed", r"sanguin\w* (?:\w+ ){0,2}(?:un sacco|tantissimo|parecchio|senza sosta)"),
    ("it", "stroke", r"non (?:muove|riesce a muovere) (?:il |la )?(?:braccio|gamba|lato)"),
    # Turkish
    ("tr", "chest", r"kalbim (?:\w+ )?(?:sikis\w*|agri\w*)|gogsum\w* (?:\w+ ){0,2}(?:sikis\w*|yan\w*)"),
    ("tr", "breath", r"nefes\w* (?:\w+ )?(?:kesil\w*|yetmiyor)"),
    ("tr", "bleed", r"(?:cok|fazla|asiri) (?:\w+ )?kan (?:kaybed\w*|geliyor|akiyor)|kan (?:\w+ )?(?:dinmiyor|kesilmiyor)"),
    ("tr", "stroke", r"(?:agzi|agzim|yuzu|yuzum) (?:\w+ )?(?:yamul\w*|carpil\w*)"),
    ("tr", "resus", r"kendinde degil|ayilmiyor"),
    # Polish
    ("pl", "chest", r"klat(?:k|c)\w* piersiow\w*|boli mnie (?:w )?klat(?:k|c)\w*|bol (?:w )?klat(?:k|c)e"),
    ("pl", "chest", r"(?:kluje|klucie|piecze|gniecie|uciska) (?:\w+ ){0,2}(?:w )?(?:sercu|serce|klatce|piersi)"),
    ("pl", "stroke", r"opad\w* kacik\w*|kacik\w* (?:ust )?opad\w*|belko(?:t|c)\w*"),
    ("pl", "stroke", r"mowi (?:\w+ )?niewyrazn\w*|(?:reka|noga) (?:\w+ )?bezwladn\w*|bezwladn\w* (?:reka|noga)"),
    ("pl", "breath", r"brak (?:mi )?(?:tchu|powietrza)|nie (?:moge|moze) (?:\w+ )?zlapac (?:tchu|oddechu|powietrza)"),
    ("pl", "bleed", r"krew (?:\w+ ){0,3}(?:nie przestaje|nie ustaje|tryska|leje sie)"),
    ("pl", "crisis", r"nie chce mi sie zyc|nie chce (?:juz )?zyc"),
    # Persian
    ("fa", "chest", r"سینه ?(?:ام|اش|م)? (?:[^ ]+ ){0,2}درد"),
    ("fa", "chest", r"سینه ?(?:ام|اش|م)? (?:[^ ]+ ){0,2}(?:تیر می ?کشد|تیر میکشه|فشار|سنگین)"),
    ("fa", "stroke", r"(?:صورت|دهان|دهن)(?:م|ش|ام|اش)? (?:[^ ]+ ){0,2}کج"),
    ("fa", "stroke", r"(?:یک|یه) طرف (?:[^ ]+ ){0,2}(?:بی ?حس|فلج|ضعیف)"),
    ("fa", "breath", r"نفسم (?:[^ ]+ ){0,2}(?:بند|تنگ)|خفه"),
    ("fa", "bleed", r"خون (?:[^ ]+ ){0,2}(?:قطع نمی ?شه|قطع نمیشه|بند نمیشه)|خون ?ریزی (?:[^ ]+ )?(?:زیاد|شدید)"),
    ("fa", "crisis", r"(?:نمی ?خوام|نمی ?خواهم) (?:[^ ]+ ){0,2}زندگی کنم|خودمو بکشم"),
    # Urdu
    ("ur", "chest", r"دل (?:میں|مین) (?:[^ ]+ ){0,2}درد"),
    ("ur", "breath", r"سانس (?:[^ ]+ ){0,3}(?:مشکل|دقت|تکلیف|رک)"),
    ("ur", "bleed", r"خون (?:[^ ]+ ){0,2}(?:بہہ رہا|بہہ رہی|نکل رہا|رک نہیں|بند نہیں)"),
    ("ur", "bleed", r"خون (?:[^ ]+ )?نہیں رک|خون (?:[^ ]+ )?بند نہیں"),
    ("ur", "stroke", r"ایک طرف (?:کا |کی |کے )?(?:ہاتھ|پاؤں|پیر|جسم).{0,24}(?:کام نہیں|سن|کمزور)"),
    # Indonesian
    ("id", "stroke", r"(?:wajah|mulut|muka)(?:nya)? (?:\w+ ){0,3}(?:mencong|miring|perot)"),
    ("id", "resus", r"tidak sadar|gak sadar|nggak sadar|tak sadarkan diri"),
    ("id", "chest", r"dada(?:ku|nya)? (?:\w+ ){0,2}(?:nyeri|sakit|sesak|berat|tertekan)"),
    ("id", "breath", r"(?:napas|nafas)(?:nya| saya| aku)? (?:\w+ )?(?:sesak|berat|susah|sulit|tersengal)"),
    ("id", "bleed", r"darah(?:nya)? (?:\w+ ){0,2}(?:ngucur|mengucur|terus keluar|gak berhenti|nggak berhenti)"),
    # Filipino
    ("tl", "chest", r"(?:masakit|sakit|kirot|sumasakit) (?:\w+ ){0,2}(?:ng|sa|ang) (?:aking )?dibdib|dibdib ko (?:ay )?(?:masakit|sumasakit|naninikip)|(?:masakit|sumasakit|kirot) (?:\w+ ){0,2}chest"),
    ("tl", "chest", r"nakadagan sa dibdib|(?:dibdib|chest) ko (?:ay )?(?:\w+ )?(?:masakit|sumasakit|naninikip|mabigat)"),
    ("tl", "breath", r"(?:di|hindi) (?:ako |siya |sya |na )?maka ?hinga"),
    ("tl", "bleed", r"(?:hindi|ayaw|di) (?:\w+ )?tumi(?:gil|tigil) (?:ang|ng) (?:pagdurugo|dugo)|dugo (?:ay )?(?:hindi|ayaw) tumi(?:gil|tigil)|ang daming dugo"),
    ("tl", "bleed", r"(?:sobrang dami|napakaraming|sobrang daming) (?:ng )?dugo|dugo (?:\w+ ){0,2}(?:hindi tumitigil|tuloy tuloy)"),
    ("tl", "crisis", r"(?:ayoko|ayaw ko) (?:na|nang) (?:mabuhay|magbuhay)|gusto ko na mamatay"),
    ("tl", "stroke", r"(?:nanghihina|manhid|hindi maigalaw) (?:ang )?(?:kaliwang|kanang|isang) (?:braso|binti|kamay|paa|bahagi)"),
    ("tl", "resus", r"hindi (?:\w+ )?(?:magising|magigising|nagigising)|ayaw (?:magising|gumising)"),
    ("tl", "overdose", r"(?:nakalunok|lumunok|nilunok) (?:ng |ang )?(?:\w+ ){0,2}(?:baterya|battery|magnet)"),
    ("tl", "altered", r"biglang nalilito|nalilito (?:siya|sya)|hindi (?:kami |ako )?makilala"),
    ("tl", "head", r"(?:tumama|nauntog|bumagsak).{0,30}ulo.{0,60}(?:pampalabnaw|blood thinner)"),
    # Bengali
    ("bn", "chest", r"বুক (?:[^ ]+ ){0,2}(?:ব্যথা|চাপ|ধড়ফড়|ভারী)"),
    ("bn", "breath", r"(?:দম|শ্বাস) (?:[^ ]+ ){0,2}(?:নিতে পারছি না|নিতে পারছে না|বন্ধ|আটকে)"),
    ("bn", "bleed", r"(?:অনেক|প্রচুর) রক্ত"),
    ("bn", "crisis", r"বাঁচতে (?:ইচ্ছা|ইচ্ছে) (?:করে|করছে) না|বাঁচতে চাই না"),
    ("bn", "stroke", r"এক (?:দিক|পাশ) (?:[^ ]+ ){0,2}(?:অবশ|দুর্বল)"),
    # Romanized (typed in Latin letters), matched on accent-free text with word edges
    ("hi_latn", "chest", r"(?:seene|sine|seena|sina|chhati|chati|chaati) (?:\w+ ){0,3}(?:dard|dabav|dabaav|jakdan|bhari)|dil ka daura"),
    ("hi_latn", "breath", r"saa?ns? (?:\w+ ){0,2}(?:nahi|nahin|nhi|nai) (?:aa|le pa|li ja)\w*|saa?ns? (?:lene (?:mein|me) )?(?:\w+ ){0,2}(?:taklif|takleef|dikkat|pareshani|mushkil)|saa?ns? phool|dam ghut"),
    ("hi_latn", "breath", r"(?:saa?ns?|breath\w*) (?:\w+ ){0,3}(?:problem|taklif|takleef|dikkat|pareshani|mushkil)"),
    ("hi_latn", "bleed", r"khoo?n (?:\w+ ){0,2}(?:ruk nahi|ruk nahin|ruk nhi|band nahi|band nahin|beh raha|bah raha|beh rahi|bah rahi|nikal raha)|bahut (?:zyada |jyada )?khoo?n"),
    ("hi_latn", "bleed", r"khoo?n (?:\w+ ){0,2}(?:nahi|nahin|nhi) ruk"),
    ("hi_latn", "crisis", r"(?:marna|mar jana|mar jaana) chaht\w*|khudkh?ushi|aatmahatya|atmahatya|(?:jeena|jina) nahi chaht\w*|apni jaan (?:le|lena|dena)|khud ko (?:maar|mar|nuksan|nuksaan)"),
    ("hi_latn", "stroke", r"(?:chehra|chehera|munh|muh|moonh) (?:\w+ ){0,3}(?:tedha|tedhi|terha|latak\w*|tircha)|lakwa|laqwa|ek taraf (?:kamzori|sun|sunn)"),
    ("hi_latn", "resus", r"behosh|be hosh|hosh (?:mein )?nahi"),
    ("ar_latn", "chest", r"(?:alam|wja3|waja3|wa?ja3) (?:\w+ ){0,2}(?:fi |b)?(?:sadri|sadr|el ?sadr|is ?sadr)|sadri (?:\w+ )?(?:byewja3ni|biwja3ni|yewja3ni|wja3ni)"),
    ("ar_latn", "breath", r"(?:msh|mish|mush|mo|ma|mani) (?:2ader|qader|aader|ader|qadra|2adra|adra) (?:atnaff?as|etnaff?as)|(?:di2|diq|dee2|deeq) (?:fi )?(?:nafas|tanaffos|nafs)|ekhtena2|ekhtinaq"),
    ("ar_latn", "bleed", r"nazif (?:\w+ )?(?:kteer|kthir|ktir|shadid|2awi|qawi)|(?:el ?dam|dam) (?:\w+ )?(?:ma|mosh|msh|mish) (?:byo2af|bywa2ef|biwa2if|wa2if|waqif)"),
    ("ar_latn", "crisis", r"(?:bdi|bade|biddi|abi|abgha|3ayez|3ayz|3awez) (?:\w+ )?(?:intehar|intihar|entehar|amout|mout|moot|amoot)|(?:a2tol|aqtol|2etel|aktol) (?:nafsi|7ali|hali)|intihar|intehar|entehar"),
    ("ar_latn", "stroke", r"jalta|sakta dimaghiya|wejho (?:mayel|ma3wouj)"),
    ("ar_latn", "stroke", r"(?:wesho|wishu|weshu|wajho|wejho) (?:\w+ )?(?:mayel|ma2loob|a3waj|m3awaj)"),
    ("ar_latn", "resus", r"(?:ma|mosh|msh) (?:by|b)?yetnaff?as|fa2ed (?:el ?)?wa3i|faqid (?:al ?)?wa3i"),
    ("ar_latn", "resus", r"(?:mesh|msh|mish|ma) (?:bifoo2|byefi2|bifou2|byes7a|bis7a|biyrod)"),
    ("zh_latn", "chest", r"xiong ?(?:kou|bu)? ?(?:hen |hao |fei chang |te bie )?(?:teng|tong|men)|xin ?(?:zang|kou) ?(?:hen |hao )?(?:teng|tong)"),
    ("zh_latn", "breath", r"chuan bu (?:guo|shang|chu) ?(?:lai )?qi|hu ?xi ?kun ?nan|bu neng hu ?xi|tou bu guo qi"),
    ("zh_latn", "bleed", r"liu xue bu zhi|xue (?:zhi bu zhu|ting bu xia|liu bu ting|yi zhi liu)|da chu xue"),
    ("zh_latn", "crisis", r"(?:xiang|yao) zi ?sha|bu xiang huo|wo xiang si"),
    ("zh_latn", "stroke", r"zhong ?feng|zui wai|lian wai|shuo hua bu qing|ban shen bu sui"),
    ("zh_latn", "resus", r"hun ?mi|jiao bu xing|bu xing ren shi|mei (?:you )?hu xi"),
    ("ru_latn", "chest", r"bol(?:'|i)? v grudi|bolit (?:v )?grud\w*|grud\w* bolit|davit (?:v )?grudi|infarkt"),
    ("ru_latn", "breath", r"ne (?:mogu|mozhet) dyshat|(?:trudno|tyazhelo) dyshat|zadykha\w*|ne k?hvataet vozduk?ha|odyshka"),
    ("ru_latn", "bleed", r"krov\w* ne ostanavliva\w*|sil'?noe krovotechenie|mnogo krovi"),
    ("ru_latn", "crisis", r"k?hochu umeret|pokonchit s soboj|ubit sebya|ne k?hochu zhit|samoubijstv\w*"),
    ("ru_latn", "stroke", r"insul'?t|perekosilo li(?:c|ts)o|li(?:c|ts)o perekos\w*"),
    ("ru_latn", "resus", r"ne dyshit|bez soznaniya|poteryal\w* soznanie"),
    ("ja_latn", "chest", r"mune ga (?:\w+ )?(?:itai|kurushii)|shinzou hossa"),
    ("ja_latn", "breath", r"iki ga (?:dekinai|kurushii|dekimasen)|ikigurushii|kokyuu? ga (?:dekinai|kurushii)|kokyuu? konnan"),
    ("ja_latn", "bleed", r"chi ga tomaranai|shukketsu ga (?:hidoi|tomaranai)"),
    ("ja_latn", "crisis", r"shinitai|jisatsu|kietai|ikitakunai"),
    ("ja_latn", "stroke", r"noukousoku|nousocchuu|ro?retsu ga mawaranai"),
    ("ja_latn", "resus", r"ishiki ga nai|ishiki fumei|hannou ga nai"),
    ("ko_latn", "chest", r"gaseum(?:i|e)? (?:\w+ )?(?:apa|apayo|apeuda|dapdap)\w*|simjangmabi"),
    ("ko_latn", "breath", r"sum(?:eul|i)? (?:mot ?swi|an swi|makh?yeo)\w*|hoheup ?gonran"),
    ("ko_latn", "bleed", r"piga (?:an meom|meomchuji anh|gyesok na)\w*"),
    ("ko_latn", "crisis", r"jukgo ?sip\w*|jasal"),
    ("ko_latn", "stroke", r"noejoljung|jungpung"),
    ("ko_latn", "resus", r"uisigi eops\w*|uisik eops\w*"),
    ("fa_latn", "chest", r"(?:sine|sineh)(?: ?am| ?ash| ?m)? (?:\w+ ){0,2}dard|dard(?:e)? (?:\w+ )?sine"),
    ("fa_latn", "breath", r"nemi?(?:tunam|toonam|tavanam) nafas (?:bekesham|bekeshe)|nafasam (?:bala )?nemiad|tangi(?:ye)? nafas|nafas tangi"),
    ("fa_latn", "bleed", r"khoo?n ?rizi (?:shadid|ziad|ziyad)|khoo?n band nemi(?:ad|she)"),
    ("fa_latn", "crisis", r"khod ?koshi|mikha+m bemiram|nemikham zende"),
    ("fa_latn", "stroke", r"sekte(?:ye)? maghzi|(?:soorat|surat|dahan)(?:am|esh)? kaj"),
    ("fa_latn", "resus", r"bi ?hoo?sh|bihush|az hoo?sh raft"),
    ("bn_latn", "chest", r"buke? (?:\w+ ){0,2}(?:betha|bytha|byatha|batha|chap)"),
    ("bn_latn", "breath", r"(?:shash|shas|shwas|nishash|nisshash) (?:nite|nete) (?:\w+ )?(?:kosto|koshto|kashto|parchi ?na|parche na)|shash ?ko(?:s|sh)to|dom bondho"),
    ("bn_latn", "bleed", r"rokto (?:\w+ )?(?:bondho hocche na|thamche ?na)|onek rokto|prochur rokto"),
    ("bn_latn", "crisis", r"atto?hotta|atmohotta|more jete chai|morte chai|bachte chai na"),
    ("bn_latn", "stroke", r"mukh (?:\w+ )?(?:beke|banka|beka)\w*|pokkhaghat"),
    ("bn_latn", "resus", r"ogyan|ojnan|oggan|gyan nei|jnan nei"),

    # Categories from the first blind test, in every language: a suicide plan with a place or a
    # means, a goodbye or suicide note, and swallowing on purpose; a household chemical swallowed;
    # a child's breathing distress (ribs sucking in, a high noise breathing in, drooling and cannot
    # swallow); and "not breathing" in words the lists above missed.
    ("es", "crisis", r"cartas? de despedida|nota suicida|(?:deje|escribi|tengo escrita|ya escribi) (?:una |unas |mi |mis )?(?:carta|cartas|nota|notas) (?:de despedida|para (?:mi familia|mis hijos|mis papas|todos))"
                     r"|(?:tirarme|aventarme|lanzarme|arrojarme) (?:de|del|desde|por) (?:un |una |el |la |lo alto de )?(?:puente|edificio|techo|azotea|balcon|ventana|estacionamiento|piso)"
                     r"|(?:tirarme|aventarme|lanzarme) (?:al|a las|frente al|delante del) (?:tren|metro|vias|carro|coche|trafico)|ahorcarme|colgarme (?:de|con) (?:una |la |el )?(?:soga|cuerda|cinturon|viga)"
                     r"|(?:pegarme|darme) un tiro|dispararme|(?:cansad[oa]|hart[oa]) de vivir|(?:juntando|guardando|tengo guardadas) (?:las |mis )?pastillas"
                     r"|(?:me tome|tome|me trague|trague|bebi|me bebi) (?:\w+ ){0,5}(?:a proposito|adrede|para morir(?:me)?|para matarme|para no despertar)|(?:a proposito|adrede) (?:me )?(?:tome|trague|bebi)"),
    ("es", "overdose", r"(?:bebio|bebi|se tomo|me tome|trago|se trago|me trague|ingirio|comio|se comio|probo|chupo|mordio) (?:\w+ ){0,3}"
                       r"(?:cloro|cloralex|clorox|lejia|blanqueador|limpiador\w*|destapacanos|amoniaco|detergente|jabon de (?:ropa|trastes|lavar)|capsulas? de (?:detergente|lavar|ropa)"
                       r"|veneno|raticida|insecticida|anticongelante|gasolina|thinner|acido|aguarras|sosa caustica|productos? de limpieza|liquido de limpieza|algo de debajo del (?:fregadero|lavabo))"),
    ("es", "breath", r"se le hunden las costillas|se (?:le|me) hunde (?:el pecho|la panza|entre las costillas)|se le marcan las costillas (?:al|cuando) respira"
                     r"|(?:hace|hacia) (?:un )?(?:ruido|silbido|chillido|sonido) (?:\w+ ){0,2}(?:al|cuando) (?:respira|respirar|jala aire)|respira con (?:ruido|silbido|chillido)"
                     r"|(?:babea|babeando|se le cae la baba) (?:\w+ ){0,3}no (?:puede|puedo) tragar|no (?:puede|puedo) tragar (?:\w+ ){0,3}(?:babea\w*|ni (?:la )?saliva|su saliva|mi saliva)|aleteo nasal"),
    ("es", "resus", r"no (?:esta|estaba) respirando|no creo que (?:este|estuviera) respirando|no se si (?:esta|sigue) respirando|labios (?:morad\w*|azul\w*)"),
    ("fr", "crisis", r"lettres? d'adieu|mot d'adieu|(?:me jeter|me lancer|me balancer) (?:d'un|du|de la|depuis le|depuis un|par la) (?:pont|toit|immeuble|balcon|fenetre|falaise|parking)|sauter (?:d'un|du) pont"
                     r"|me jeter sous (?:un|le) (?:train|metro|camion)|me pendre|me tirer une balle|(?:fatigue|marre) de vivre"),
    ("fr", "overdose", r"(?:bu|avale|ingere|mange|bois|avaler) (?:[\w']+ ){0,3}(?:(?:l')?eau de javel|javel|detergent|produit (?:menager|de nettoyage)|deboucheur|destop|ammoniaque"
                       r"|mort aux rats|poison|antigel|essence|insecticide|(?:pastille|dosette|capsule)s? de lessive|lessive)"),
    ("fr", "breath", r"tirage (?:intercostal|sus.sternal|respiratoire)|(?:il|elle) fait du tirage|(?:les )?cotes (?:qui )?se creusent|stridor"
                     r"|bruit (?:aigu |strident )?(?:en|quand (?:il|elle)) (?:respire|inspire|respirant|inspirant)|(?:bave|baver) (?:\w+ ){0,3}(?:n'arrive pas|ne peut pas|ne peux pas) (?:a )?avaler"),
    ("pt", "crisis", r"carta de despedida|bilhete (?:de despedida|suicida)|(?:me jogar|me atirar) (?:da|de uma|do|de um|de cima d[ao]) (?:ponte|predio|telhado|janela|viaduto|sacada|laje)|pular d[ae] (?:uma )?ponte"
                     r"|me jogar na frente d[oe] (?:trem|metro|carro|onibus|caminhao)|me enforcar|me dar um tiro|(?:cansad[oa]|cheio|cheia) de viver"),
    ("pt", "overdose", r"(?:bebeu|bebi|tomou|tomei|engoliu|engoli|ingeriu|comeu|mordeu) (?:\w+ ){0,3}(?:agua sanitaria|candida|cloro|alvejante|desinfetante|detergente|veneno|chumbinho"
                       r"|soda caustica|limpador|desentupidor|amonia|gasolina|querosene|inseticida|raticida|capsula de lavar roupa|sabao)"),
    ("pt", "breath", r"costelas (?:\w+ ){0,2}(?:afundando|afundam|aparecendo quando respira)|(?:chiado|barulho|assobio) (?:\w+ ){0,2}(?:ao|quando) (?:respira|puxa o ar|inspira)"
                     r"|babando (?:\w+ ){0,3}nao (?:consegue|consigo) engolir"),
    ("tl", "crisis", r"(?:sulat|liham) (?:ng |na )?(?:paalam|pamamaalam)|suicide note|tatalon (?:\w+ )?(?:sa|mula sa|galing sa) (?:tulay|building|gusali)"
                     r"|magbigti|nagbigti|(?:pagod|sawa) na (?:akong )?mabuhay"),
    ("tl", "overdose", r"(?:uminom|ininom|nainom|nilunok|lumunok|nakalunok|kinain|nakainom) (?:ng |ang )?(?:\w+ ){0,2}(?:zonrox|bleach|clorox|muriatic|asido|lason|pamatay ng (?:daga|ipis|lamok)"
                       r"|insecticide|baygon|gasolina|kerosene|gaas|panlinis|detergent|sabon panlaba)"),
    ("tl", "breath", r"lumulubog (?:ang )?(?:tadyang|dibdib)|(?:humuhuni|may tunog|sumisipol) (?:\w+ ){0,2}(?:kapag|pag|habang) (?:humihinga|huminga)"
                     r"|naglalaway (?:\w+ ){0,3}(?:hindi|di) (?:makalunok|makalulon)"),
    ("de", "crisis", r"abschiedsbrief\w*|abschiedsnachricht\w*|(?:von|vom) (?:der |einer |dem |einem )?(?:brucke|dach|hochhaus|parkhaus|balkon|fenster) (?:zu )?springen"
                     r"|vor (?:den|einen) zug (?:zu )?(?:springen|werfen)|mich (?:zu )?erhangen|mich aufhangen|mich erschiessen|lebensmude"),
    ("de", "overdose", r"(?:getrunken|geschluckt|gegessen|eingenommen|trank|schluckte) (?:\w+ ){0,3}(?:bleiche|bleichmittel|chlorreiniger|reiniger|abflussreiniger|rohrreiniger|putzmittel"
                       r"|waschmittel|spulmittel|spultab\w*|rattengift|gift|frostschutz\w*|benzin|lampenol|ammoniak)|(?:bleiche|bleichmittel|chlorreiniger|abflussreiniger|rohrreiniger"
                       r"|putzmittel|waschmittel|spulmittel|spultab\w*|rattengift|frostschutz\w*|benzin|lampenol|ammoniak) (?:\w+ ){0,2}(?:getrunken|geschluckt|gegessen)"),
    ("it", "crisis", r"letter[ae] d'addio|biglietto d'addio|(?:buttarmi|gettarmi|lanciarmi) (?:dal|da un|da una|dalla|giu dal|giu da un) (?:ponte|tetto|palazzo|balcone|finestra|parcheggio)"
                     r"|buttarmi sotto (?:un|il) (?:treno|metro)|impiccarmi|spararmi|stanc[oa] di vivere"),
    ("it", "overdose", r"(?:bevuto|bevve|ingerito|ingoiato|inghiottito|mangiato) (?:[\w']+ ){0,3}(?:candeggina|varechina|ammoniaca|detersivo|veleno|topicida|antigelo|benzina"
                       r"|sgorgatore|disinfettante|capsul\w* (?:di|del|per) (?:detersivo|lavatrice|bucato))"),
    ("tr", "crisis", r"veda mektubu|intihar notu|(?:kopruden|binadan) (?:atla\w*|kendimi at\w*)|kendimi (?:catidan|balkondan|pencereden) at\w*|kendimi (?:asmak|asacagim|asmayi|asarim)"
                     r"|kendimi vur\w*|yasamaktan (?:bikt\w*|yoruldum|sikildim)"),
    ("tr", "overdose", r"(?:camasir suyu|kezzap|deterjan|temizlik (?:malzemesi|ilaci)|fare zehiri|zehir|antifriz|benzin|tiner|lavabo acici|bulasik tableti) (?:\w+ )?(?:ict\w*|yut\w*|yedi|yemis\w*)"),
    ("pl", "crisis", r"listy? pozegnaln\w*|(?:skoczyc|rzucic sie) z (?:mostu|dachu|wiezowca|balkonu|okna|parkingu)|rzucic sie pod (?:pociag|samochod)|powiesic sie|zastrzelic sie"
                     r"|zmeczon\w* zyciem|mam dosc zycia"),
    ("pl", "overdose", r"(?:wypil\w*|polknal\w*|polknela|zjadl\w*) (?:\w+ ){0,3}(?:wybielacz\w*|domestos\w*|kret\w*|srodek czyszczac\w*|plyn do (?:czyszczenia|naczyn|prania|udraznia\w*)"
                       r"|trutk\w*|trucizn\w*|detergent\w*|kapsulk\w* do prania|plyn do chlodnic\w*|benzyn\w*|rozpuszczalnik\w*)"),
    ("id", "crisis", r"surat (?:perpisahan|wasiat|bunuh diri)|(?:terjun|melompat) dari (?:atas )?(?:jembatan|gedung)|gantung diri|(?:lelah|capek|cape) hidup"),
    ("id", "overdose", r"(?:minum|meminum|menelan|nelen|makan|tertelan|keminum) (?:\w+ ){0,3}(?:pemutih|bayclin|cairan pembersih|pembersih (?:lantai|toilet|kamar mandi)|deterjen|racun"
                       r"|racun tikus|obat nyamuk|baygon|bensin|minyak tanah|soda api|karbol|wipol|porstex)"),
    ("vi", "crisis", r"thư tuyệt mệnh|thu tuyet menh|thư từ biệt|(?:viết|để lại) (?:[^ ]+ ){0,2}(?:thư|lá thư) (?:từ biệt|tuyệt mệnh|cho gia đình)|nhảy lầu|nhay lau|nhảy sông|nhay song"
                     r"|nhảy (?:từ|xuống) (?:[^ ]+ ){0,2}(?:cầu|tầng|nóc nhà|sân thượng|ban công)|nhay (?:tu|xuong) (?:[^ ]+ ){0,2}(?:cau|tang|noc nha|san thuong)|treo cổ|treo co"
                     r"|chán sống|chan song|cố tình (?:uống|nuốt)|co tinh (?:uong|nuot)|(?:uống|nuốt) (?:[^ ]+ ){0,5}(?:để chết|để tự tử)|(?:uong|nuot) (?:[^ ]+ ){0,5}(?:de chet|de tu tu)"),
    ("vi", "overdose", r"uống (?:nhầm |phải |cả |hết )?(?:[^ ]+ ){0,2}(?:nước tẩy|thuốc tẩy|chất tẩy|nước rửa (?:chén|bát|bồn cầu|toilet)|nước javen|javel|thuốc trừ sâu|thuốc diệt (?:chuột|cỏ|côn trùng)"
                       r"|thuốc chuột|xăng|dầu hỏa|axit|xút)|uong (?:nham |phai )?(?:[^ ]+ ){0,2}(?:nuoc tay|thuoc tay|chat tay|nuoc rua (?:chen|bat)|thuoc tru sau|thuoc diet (?:chuot|co)"
                       r"|thuoc chuot|xang|dau hoa)|nuốt (?:phải )?(?:[^ ]+ ){0,2}(?:đồng xu|viên bi|nam châm)|nuot (?:phai )?(?:[^ ]+ ){0,2}(?:dong xu|vien bi|nam cham)"),
    ("vi", "breath", r"rút lõm (?:lồng ngực|ngực|liên sườn|hõm ức)|rut lom (?:long nguc|nguc|lien suon)|(?:thở|tho) (?:[^ ]+ ){0,2}(?:rút lõm|rut lom|rít|rit)"
                     r"|chảy nước miếng (?:[^ ]+ ){0,3}không nuốt được|chay nuoc mieng (?:[^ ]+ ){0,3}khong nuot duoc|không nuốt được (?:[^ ]+ ){0,3}(?:chảy nước miếng|nước bọt)"),
    ("vi", "resus", r"(?:không|khong) (?:còn |con )?(?:thở|tho)(?! được| duoc| nổi| noi| ra| bình| binh)"),
    ("zh", "crisis", r"遗书|遺書|绝笔|絕筆|跳楼(?!价|價)|跳樓(?!價)|跳桥|跳橋|跳河|从(?:楼|樓|桥|橋|天台|阳台|陽台|屋顶|屋頂|大楼|大樓).{0,2}跳下|卧轨|臥軌|上吊|割腕"
                     r"|故意(?:喝|吃|吞)|(?:喝|吃|吞).{0,8}(?:想死|为了死|為了死)"),
    ("zh", "overdose", r"(?:喝|吞|吃|误服|誤服|误食|誤食|误喝|誤喝)(?:了|下|进|進)?.{0,4}(?:漂白|消毒液|84消毒|洗洁精|洗潔精|洁厕|潔廁|清洁剂|清潔劑|洗衣液|洗衣球|洗衣凝珠"
                       r"|农药|農藥|敌敌畏|敵敵畏|百草枯|老鼠药|老鼠藥|鼠药|鼠藥|杀虫剂|殺蟲劑|汽油|煤油|硫酸|盐酸|鹽酸|强酸|强碱|強鹼|通渠|疏通剂|疏通劑)"),
    ("zh", "breath", r"三凹|肋骨(?:间|間|下)?.{0,2}(?:凹|陷|吸)(?:进去|進去|下去)?|胸口凹陷|吸气.{0,4}(?:尖|怪|呼噜|呼嚕|嘶|哨)(?:声|聲|音)|喉鸣|喉鳴"
                     r"|流口水.{0,6}(?:咽不下|吞不下|不能吞|咽不了|吞不了)|(?:咽不下|吞不下|吞不了|咽不了).{0,6}口水"),
    ("ja", "crisis", r"遺書|(?:橋|ビル|屋上|ベランダ|マンション|駐車場)から飛び降り|飛び降り(?:たい|る|よう|自殺)|首を吊|首吊り|電車に飛び込|生きるのに疲れ"),
    ("ja", "overdose", r"(?:漂白剤|ハイター|洗剤|ジェルボール|殺虫剤|農薬|殺鼠剤|灯油|ガソリン|洗浄剤|パイプユニッシュ|塩素|(?<!中)毒)(?:を|が)?.{0,4}(?:飲ん|飲み|食べ|誤飲|口に入れ)"),
    ("ko", "crisis", r"유서|(?:다리|옥상|아파트|건물|베란다|주차장)에서 (?:뛰어내리|투신)|투신|목을 매|목매|사는 게 (?:너무 )?지쳐|살기 지쳐"),
    ("ko", "overdose", r"(?:락스|표백제|세제|세정제|농약|살충제|쥐약|등유|휘발유|독극물|배수구 세정제)(?:을|를)? ?(?:마셨|삼켰|먹었)"),
    ("ar", "crisis", r"رسالة وداع|رسالة انتحار|ورقة وداع|(?:ارمي|أرمي|بارمي|بأرمي|برمي) (?:نفسي|حالي) (?:من|تحت)"
                     r"|(?:اشنق|أشنق) (?:نفسي|حالي)"
                     r"|(?:اطلق|أطلق) (?:النار|الرصاص) على (?:نفسي|حالي)|(?:تعبت|زهقت|مليت) من (?:الحياة|العيش|حياتي)"
                     r"|(?:عن قصد|متعمد|بقصد|عمدا)(?: [^ ]+){0,4} (?:شربت|بلعت|اكلت|أكلت|اخذت|أخذت)|(?:شربت|بلعت|اكلت|أكلت|اخذت|أخذت)(?: [^ ]+){0,5} (?:عن قصد|عمدا|عشان اموت|عشان أموت|لكي أموت)"),
    ("ar", "overdose", r"(?:شرب|شربت|بلع|بلعت|اكل|اكلت|أكل|أكلت|تناول|تناولت)(?: [^ ]+){0,2} (?:كلوركس|كلوروكس|كلور|مبيض|منظف|منظفات|ديتول|فلاش|مطهر|\bسم\b|مبيد|مبيدات|بنزين|كاز|كيروسين"
                       r"|ماء النار|مويه نار|صودا كاوية)"),
    ("ar", "breath", r"(?:ضلوعه|ضلوعها|اضلاعه|اضلاعها|صدره|صدرها) (?:[^ ]+ )?(?:تدخل|داخلة|يدخل|ينسحب|تنسحب|بيدخل|بتدخل)|صوت (?:صفير|حاد|غريب) (?:[^ ]+ )?(?:مع|وقت|لما|عند) (?:يتنفس|تتنفس|النفس|التنفس)"
                     r"|(?:يسيل|سايل|تسيل) (?:لعاب|ريال|ريق)(?:ه|ها)? (?:[^ ]+ ){0,3}(?:ما|مش|مو) (?:يقدر|تقدر|قادر|قادرة) (?:يبلع|تبلع)"),
    ("ar", "resus", r"(?:ما|مش|مو) (?:اظن|أظن|اعتقد|أعتقد|متأكد) (?:انه|إنه|انها|إنها|ان|إن)? ?(?:يتنفس|تتنفس|بيتنفس|بتتنفس)"),
    ("fa", "crisis", r"نامه (?:خداحافظی|وداع)|یادداشت خودکشی|وصیت ?نامه (?:نوشتم|نوشته ام)|(?:از|از روی) (?:پل|پشت ?بام|ساختمان|بالکن) (?:بپرم|پریدن|بپرد)"
                     r"|(?:خودم ?(?:را|رو|و)?|خودمو) دار بزنم|حلق ?آویز|از زندگی خسته (?:شده ?ام|شدم)|خسته از زندگی"),
    ("fa", "overdose", r"(?:وایتکس|سفید ?کننده|مایع ظرفشویی|جوهر ?نمک|\bسم\b|مرگ ?موش|حشره ?کش|بنزین|نفت|اسید|شوینده|پودر لباسشویی)(?: [^ ]+){0,2} (?:خورد|خوردم|خورده|نوشید|نوشیدم|نوشیده|قورت)"),
    ("ur", "crisis", r"خودکشی (?:کا )?نوٹ|الوداعی خط|آخری خط|(?:پل|عمارت|بلڈنگ) سے (?:کود|چھلانگ)|پھانسی (?:لگا|لے)|خود کو گولی|زندگی سے تھک (?:گیا|گئی)"),
    ("ur", "overdose", r"(?:بلیچ|فینائل|ہارپک|تیزاب|زہر|چوہے مار|کیڑے مار|مٹی کا تیل|پٹرول|سرف)(?: [^ ]+){0,3} (?:پی|کھا|نگل)"),
    ("hi", "crisis", r"सुसाइड नोट|आखिरी (?:खत|चिट्ठी|पत्र)|अलविदा (?:का )?(?:खत|पत्र|चिट्ठी)|(?:पुल|बिल्डिंग|इमारत) से (?:कूद|छलांग)|फांसी (?:लगा|लगाने|लगाना)|फंदा|खुद को गोली"
                     r"|(?:जिंदगी|ज़िंदगी|जीने) से थक (?:गया|गई|चुका|चुकी)|ट्रेन के (?:आगे|सामने) (?:कूद|आ)|जान ?बूझकर (?:[^ ]+ ){0,4}(?:खा|पी|निगल)(?= |$|,|।|या|यी|ई|ये|ली|लि|गय|गई)"),
    ("hi", "overdose", r"(?:फिनाइल|फिनायल|हार्पिक|ब्लीच|तेजाब|तेज़ाब|एसिड|ज़हर|जहर|चूहे मारने की दवा|चूहे मार|कीटनाशक|कीड़े मारने की दवा|मिट्टी का तेल|केरोसिन|पेट्रोल|सर्फ|डिटर्जेंट)"
                       r"(?: [^ ]+){0,3} (?:पी|खा|निगल)(?= |$|,|।|या|यी|ई|ये|ली|लि|गय|गई)"),
    ("hi", "breath", r"(?:पसलियां|पसलियाँ|पसली|पसलियों) (?:[^ ]+ ){0,2}(?:अंदर|धंस)|सांस (?:लेते|लेने) (?:समय|वक्त|पर) (?:[^ ]+ ){0,2}(?:सीटी|घरघर|आवाज)|लार (?:[^ ]+ ){0,2}(?:टपक|बह) (?:[^ ]+ ){0,3}निगल नहीं"),
    ("hi_latn", "crisis", r"suicide note|aakhri (?:khat|chitthi|chithi)|(?:pul|building|imarat) se (?:kood|kud|koodna|kudna|chhalang)|phansi (?:laga|lagane|lagana|lagaunga|lagaungi)|fanda"
                          r"|jaan ?boojh ?kar (?:\w+ ){0,4}(?:kha|pi|pee|nigal)\w*"),
    ("hi_latn", "overdose", r"(?:phenyl|phenyle|finail|harpic|bleach|tezab|tejab|acid|zeher|zehar|jahar|chuhe (?:maarne|marne) ki dawai?|chuha maar|keetnashak|kitnashak|kerosene|mitti ka tel|petrol)"
                            r"(?: \w+){0,3} (?:pi|pee|piya|pi li|pi liya|kha li|kha liya|kha gaya|kha gayi|khaya|khayi|nigal\w*)"
                            r"|(?:battery|batteri|cell|magnet|chumbak|sikka) (?:\w+ ){0,2}nigal\w*|nigal (?:\w+ ){0,2}(?:battery|batteri|magnet|chumbak)"),
    ("bn", "crisis", r"সুইসাইড নোট|শেষ চিঠি|বিদায়ী চিঠি|(?:ব্রিজ|বিল্ডিং|সেতু) থেকে (?:লাফ|ঝাঁপ)|গলায় দড়ি|ফাঁসি (?:দেব|দিতে|দিয়ে|দিবো)|বাঁচতে (?:আর )?ভালো লাগে না"),
    ("bn", "overdose", r"(?:ব্লিচ|ফিনাইল|হারপিক|অ্যাসিড|বিষ|ইঁদুর মারার বিষ|কীটনাশক|কেরোসিন|পেট্রোল|সাবান|ডিটারজেন্ট)(?: [^ ]+){0,3} (?:খেয়ে|খেয়েছে|খেয়েছি|খেল|খেলো|গিলে|গিলেছে|পান)"),
    ("bn_latn", "crisis", r"suicide note|shesh chithi|fasi (?:debo|dite|diye)|golay dori"),
    ("bn_latn", "overdose", r"(?:bish|keetnashok|kerosin|kerosene|phenyl|bleach|harpic)(?: \w+){0,2} (?:kheye|kheyechhe|kheyeche|khelo|gile|gilechhe)"),
    ("ru", "crisis", r"предсмертн\w* записк\w*|прощальн\w* (?:письм\w*|записк\w*)|(?:броситься|сброситься) с (?:моста|крыши|балкона|окна|многоэтажки|парковки)|прыгнуть с моста"
                     r"|броситься под (?:поезд|машину|электричку)|повеситься|вскрыть вены|застрелиться|(?:устал\w*|надоело) жить"),
    ("ru", "overdose", r"(?:выпил\w*|проглотил\w*|съел\w*|наглотал\w*|отпил\w*) (?:\w+ ){0,3}(?:отбеливател\w*|хлорк\w*|белизн\w*|средств\w* для (?:мыть\w*|чистк\w*|унитаз\w*|труб)"
                       r"|чистящ\w*|моющ\w*|яд\w*|крысин\w*|антифриз\w*|бензин\w*|уксусн\w*|кислот\w*|капсул\w* для стирки|растворител\w*)"),
    ("ru", "breath", r"втягива\w* (?:межреберь\w*|ребр\w*|кож\w* между ребр\w*)|стридор|свист\w* (?:\w+ )?при вдохе|слюн\w* (?:\w+ ){0,3}не (?:может|могу) глотать"),
    ("ru_latn", "crisis", r"predsmertn\w* zapisk\w*|povesit\w*|prygnut s (?:mosta|kryshi)"),
    # Breathing distress from asthma, the same as the English "asthma attack" and "inhaler isn't working" rules.
    ("es", "breath", r"(?:ataque|crisis) (?:de asma|asmatica)|el (?:inhalador|nebulizador|salbutamol) no (?:me |le )?(?:sirve|funciona|hace nada|ayuda)"),
    ("fr", "breath", r"crise d'asthme|(?:la )?ventoline (?:ne )?(?:marche|fait) (?:pas|plus|rien)|l'inhalateur ne (?:marche|fait) (?:pas|plus|rien)"),
    ("pt", "breath", r"crise de asma|(?:a )?bombinha nao (?:esta )?(?:funcionando|ajudando|resolve)"),
    ("de", "breath", r"asthmaanfall|asthma.?anfall|(?:das )?(?:spray|inhalator) hilft nicht"),
    ("it", "breath", r"attacco d'asma|crisi d'asma|(?:il )?ventolin non (?:funziona|fa niente)"),
    ("tr", "breath", r"astim kriz\w*|astim atag\w*"),
    ("pl", "breath", r"atak astmy|napad astmy|inhalator nie (?:pomaga|dziala)"),
    ("id", "breath", r"serangan asma|asma(?:nya)? kambuh|inhaler(?:nya)? (?:tidak|nggak|gak) (?:mempan|membantu)"),
    ("tl", "breath", r"(?:inaatake|inatake|atake) (?:ng|sa) hika|hinihika|hindi tumatalab ang (?:inhaler|nebulizer)"),
    ("vi", "breath", r"lên cơn hen|len con hen|cơn hen (?:suyễn )?(?:nặng|cấp)|con hen (?:suyen )?(?:nang|cap)|xịt (?:[^ ]+ ){0,3}không (?:đỡ|ăn thua)|xit (?:[^ ]+ ){0,3}khong (?:do|an thua)"),
    ("zh", "breath", r"哮喘(?:发作|發作|急性发作|犯了)|(?:喷|噴|吸)了.{0,6}(?:药|藥).{0,4}(?:没用|沒用|没有用|沒有用|不管用)|一句话(?:都)?说不(?:完|全|出来)|一句話(?:都)?說不(?:完|全|出來)"),
    ("ja", "breath", r"喘息(?:の)?発作|吸入薬が効かない"),
    ("ko", "breath", r"천식 ?발작|흡입기(?:가|를)? ?(?:써도|사용해도)? ?(?:효과가 없|안 들)"),
    ("ar", "breath", r"(?:نوبة|أزمة|ازمة) ربو|البخاخ (?:ما|مش|مو) (?:نفع|ينفع|فاد|يفيد|بيفيد)|صعب (?:علي )?(?:أتنفس|اتنفس|التنفس)|(?:بصعوبة|بالعافية) (?:أتنفس|اتنفس)"
                     r"|(?:حلقي|حلقه|حلقها) (?:[^ ]+ )?(?:يتسكر|يسكر|ينسد|بيتسكر|مسكر|يضيق|بيضيق)"),
    ("fa", "breath", r"حمله ?(?:ی )?آسم|اسپری (?:اثر نمی ?کند|جواب نمی ?دهد|جواب نمیده)"),
    ("ur", "breath", r"دمہ کا (?:دورہ|حملہ)|انہیلر (?:کام نہیں|اثر نہیں)"),
    ("hi", "breath", r"(?:अस्थमा|दमे|दमा) का (?:दौरा|अटैक)|इनहेलर (?:[^ ]+ ){0,2}(?:काम नहीं|असर नहीं)"),
    ("hi_latn", "breath", r"(?:asthma|dama|dame) ka (?:daura|attack)|inhaler (?:\w+ ){0,2}(?:kaam nahi|asar nahi)"),
    ("bn", "breath", r"হাঁপানির টান|(?:অ্যাজমা|হাঁপানি) অ্যাটাক|ইনহেলার (?:[^ ]+ )?কাজ করছে না"),
    ("ru", "breath", r"приступ астмы|астматическ\w* приступ|ингалятор не помога\w*"),
    ("zh_latn", "crisis", r"tiao ?lou|shang ?diao|ge ?wan"),
    ("ja_latn", "crisis", r"isho wo kaita|tobiori(?:tai|ru|jisatsu)?|kubi wo tsur\w*"),
    ("ko_latn", "crisis", r"yuseo|tusin|mogeul mae\w*"),
    ("ar_latn", "crisis", r"risal[ae]t? wada3|ash?no2 nafsi|ashnoq nafsi|arm[ei] (?:nafsi|7ali)"),
    ("fa_latn", "crisis", r"name(?:ye)? (?:khodahafezi|veda)|khod(?:am|amo)? (?:ra |ro )?dar bezanam"),
]
for _code, _key, _alts in LEXICON_MORE:
    _flags = LEXICONS.setdefault(_code, {})
    _flags[_key] = f"{_flags[_key]}|{_alts}" if _key in _flags else _alts

# How a patient says a red flag is NOT happening, by language ("no tengo dolor de pecho",
# "胸口也不痛", "सीने में दर्द नहीं है"). triage_rules ignores a red-flag match when:
#   before  a "no" ends right where the red-flag words begin; "fill" words may sit between them
#           ("no tengo ningun | dolor de pecho"), and "join" lets one "no" cover a list
#           ("no tengo fiebre ni | dolor de pecho"). Only "or" words join: "no X and Y" can mean Y is there;
#   after   a "not" follows the red-flag words and ends the sentence, for languages that put
#           "not" after the words ("सीने में दर्द | नहीं है"), or a Korean or Japanese "not" ending;
#   keep    words right after the match that make it a complaint after all ("never had chest pain | like this");
#   inner   a "not" sits inside the matched words and the red flag still matches without it
#           ("胸口也不痛"), so a "not" the red flag needs ("no puedo respirar", "喘不过气") is kept.
# Kept narrow on purpose: missing a denial gives a false alarm; a false denial hides an emergency.
DENIAL: dict[str, dict[str, str]] = {
    # English: used for the chest pain, breathing and fainting rules.
    "en": {"before": r"no|not|never|without|denies|deny|didn'?t|did not|don'?t|do not|doesn'?t|does not|haven'?t|have not|hasn'?t|has not"
                     r"|wasn'?t|was not|isn'?t|is not|aren'?t|are not|nor|neither|zero",
           "fill": r"any|ever|even|really|actually|currently|recently|real|significant|major|have|had|has|got|get|getting|feel|felt|feeling|feels"
                   r"|notice|noticed|experience|experienced|experiencing|having|been|complain(?:ed|ing)? of|signs? of|a|an|the|my|his|her|their|more|other|bad|severe|serious",
           "join": r"or|nor|and no|and not|or any",
           # "never had chest pain LIKE THIS" and "no chest pain UNTIL tonight" are complaints
           "keep": r"(?:like|until|till|til|before|this bad|this severe|ever|usually|normally|but (?:it'?s|its|it is|it feels|feels|now|today|tonight))\b"},
    "es": {"before": r"no|sin|ni|nada de|ningun|ninguna|nunca|jamas|tampoco",
           "fill": r"tengo|tiene|tenia|tuve|he tenido|ha tenido|siento|siente|sentia|hay|habia|me|le|he|ha|han|se ha|se han|ningun|ninguna|nada de|ningun tipo de|algun"
                   r"|el|la|los|las|un|una|mi|su|nada|pensado|pensando|pienso|piensa|pensamientos de|ideas de|intencion de|ganas de|deseos de|planes de|en|de|quiero|quiere|voy a|va a|mucho|mucha|tanto",
           "join": r"o|ni",
           "inner": r"\bno\b(?! (?:me |le |te |se |lo |la )?(?:para\w*|deja\w*|pued\w*|podia|aguant\w*|quita\w*|va|iba|mejora\w*|cede|calma|detiene|pasa|respira\w*|responde|reacciona|despierta"
                    r"|sab\w*|creo|estoy|veo|mueve|movia|siento|siente))|\bnunca\b|\bni\b|\btampoco\b"},
    "fr": {"before": r"pas|aucun|aucune|sans|ni|jamais|plus de|non",
           "fill": r"de|du|la|le|les|un|une|vraiment|trop|du tout|ressens|ressenti|sens|senti|ai|a|eu|envie de|intention de",
           "glue": r"d'|l'", "join": r"ou|ni", "inner": r"\b(?:pas|jamais|aucun\w*)\b"},
    "pt": {"before": r"nao|nem|sem|nenhum|nenhuma|nunca|jamais",
           "fill": r"tenho|tem|tinha|tive|sinto|sente|senti|estou|esta|to|tou|ta|estava|com|sentindo|nenhuma|nenhum|de|da|do|mais|o|a|os|as|um|uma|meu|minha|quero|vou|penso|pensei|pensando|em|vontade de",
           "join": r"ou|nem",
           "inner": r"\bnao\b(?! (?:me |se |lhe )?(?:para\w*|consig\w*|pod\w*|aguent\w*|passa|melhora|respira\w*|responde|acorda|sei|sabe|estanca|mexe))|\bnem\b|\bnunca\b"},
    "it": {"before": r"non|nessun|nessuna|nessuno|senza|niente|mai|neanche|nemmeno|ne",
           "fill": r"ho|ha|avevo|sento|sente|c'e|piu|alcun|alcuna|il|la|lo|un|una|di|del|della|voglio|vuole|penso|pensato|a|al",
           "glue": r"l'|d'|un'", "join": r"o|ne",
           "inner": r"\bnon\b(?! (?:mi |si |le |gli )?(?:riesc\w*|respira\w*|risponde|sveglia|smette|ferma|passa|muove|so|sa))|\bmai\b|\bnessun\w*\b"},
    "de": {"before": r"kein|keine|keinen|keinem|keiner|keinerlei|nicht|ohne|nie|niemals|weder|noch",
           "fill": r"mehr|wirklich|so|starke|starken|richtige|richtigen|irgendwelche|irgendeine|habe|hat|hatte|spure|fuhle|an|zu",
           "join": r"oder|noch", "inner": r"\b(?:nicht|kein\w*|nie)\b"},
    "tl": {"before": r"hindi|di|wala|walang|ni",
           "fill": r"ako|ko|siya|sya|naman|po|nang|na|ng|akong|siyang|syang|masyadong|gaanong|rin|din|nararamdaman|nakakaramdam ng|ang|kong|iniisip|naisip|balak|gusto|gustong",
           "join": r"o",
           "inner": r"\b(?:hindi|di|wala|walang)\b(?! (?:ako |siya |sya |na |ko )?(?:makahinga|maka hinga|humihinga|gumigising|magising|magigising|nagigising|tumi\w*|maigalaw|makilala|gumagalaw))"},
    "id": {"before": r"tidak|tak|nggak|gak|ga|enggak|ngga|bukan|tanpa",
           "fill": r"ada|merasa|mengalami|terasa|sama sekali|pernah|ingin|mau|pengen|berpikir|berniat|untuk|saya|aku",
           "join": r"atau|maupun", "inner": r"\b(?:tidak|tak|nggak|gak|ga|enggak)\b(?! (?:bisa|mau|berhenti|sadar\w*|merespons|ingin hidup))"},
    "pl": {"before": r"nie|bez|brak|zadnego|zadnej|zadnych|nigdy|ani",
           "fill": r"mam|ma|mialem|mialam|czuje|odczuwam|mnie|jest|bylo|zadnego|zadnej|zadnych|chce|zamierzam|mysle o|myslalem o|myslalam o",
           "join": r"ani|lub", "inner": r"\bnie\b(?! (?:moge|moze|przestaje|ustaje|oddycha|reaguje|budzi|chce (?:juz )?zyc|chce mi sie zyc))|\bnigdy\b"},
    "tr": {"before": r"hic",
           "after": r"\w{0,3} ?(?:\w+ )?(?:yok|degil|yoktur|olmadi|olmuyor|hissetmiyorum|dusunmuyorum|dusunmedim|istemiyorum|etmiyorum|etmeyecegim)(?=$|[ ,.;!?])"},
    "ru": {"before": r"не|нет|без|никакой|никаких|никакого|никакая|ни|нету",
           "fill": r"у меня|у него|у нее|чувствую|ощущаю|особо|сильно|сильной|сильных|было|хочу|собираюсь|думаю о|думал о|думала о|буду|стану",
           "join": r"или|ни", "inner": r"\b(?:не|нет|ни)\b(?! (?:могу|может|остановить|останавлива\w*|хватает|дышит|реагирует|приходит|просыпа\w*))"},
    "vi": {"before": r"không|khong|ko|chẳng|chang|chả|chưa|chua|chưa từng|chua tung|không hề|khong he",
           "fill": r"bị|bi|có|co|thấy|thay|hề|he|còn|con|gì|gi|cảm thấy|cam thay|muốn|muon|định|dinh|nghĩ đến|nghi den|nghĩ tới|nghi toi|ý định|y dinh",
           "join": r"hay|hoặc|hoac|cũng không|cung khong",
           "inner": r"\b(?:không|khong|ko|chẳng|chang|chả)\b(?! (?:ngừng|ngung|dứt|dut|cầm|cam|được|duoc|nổi|noi|ra|thể|the|tỉnh|tinh|muốn sống|muon song|nhận|nhan|chịu|chiu"
                    r"|hết|het|bớt|bot|đỡ|giảm|giam|nói|nuốt|nuot|thở|tho|cử động|cu dong))"},
    "zh": {"before": r"没有|沒有|没|沒|无|無|不|未|并不|並不|并没有|並沒有|从不|從不|从来没有|從來沒有|从没|從沒|毫无|毫無|不会|不會|绝不|絕不",
           "fill": r"想过|想過|想|要|去|过|過|有|会|會|打算|任何|什么|什麼|感到|觉得|覺得|感觉|感覺|出现|出現|再|也|都|太|这种|這種|的|明显|明顯|一点|一點",
           "join": r"或者|或|、|也没有|也沒有|也不",
           "inner": r"不(?!停|断|斷|住|了|行|得了|舒服|太舒服|适|適|对劲|對勁|正常|过来|過來|上来|上來|下去|起来|起來|动|動|能|清|醒|省|遂|出|到|下)|没有|沒有|没(?!力)|沒(?!力)|无(?!力|法)|無(?!力|法)|未"},
    "ja": {"after": r"[ぁ-ゖ]{0,2}?(?:は|が|も|とか|など)?(?:全く|まったく|特に|あまり|別に)?(?:ない|無い|ありません|ないです|なかった|なし|くない|くありません|くないです|くなかった|しない|しません|していない|してない"
                    r"|していません|考えて(?:い)?(?:ない|ません)|考えたことは(?:ない|ありません)|するつもりは(?:ない|ありません)|する気は(?:ない|ありません)|たくない|たくありません)"},
    "ko": {"after": r"[^ ]{0,3} ?(?:(?:통증|증상|생각|마음|계획|적|일|것|건|게|느낌)(?:은|는|이|가|도)? ?)?(?:없|않|아니)"},
    "ar": {"before": r"و?(?:ما|مش|مو|مب|لا|ليس|ليست|لست|لم|لن|بدون|بلا|مافي|ما في|مافيش|ما فيش|مفيش|ما عندي|ماعندي|ما عنده|ما عندها|ما فيه|لا يوجد|لا توجد|ما احس|ما أحس|ما اشعر|ما أشعر|ما حسيت)",
           "fill": r"اي|أي|ابدا|أبدا|اصلا|أصلا|شي|شيء|في|عندي|احس|أحس|افكر|أفكر|فكرت|ابي|أبي|بدي|اريد|أريد|ناوي|راح|رح",
           "glue": r"ال|بال|لل|وال|ب|ل|ف", "join": r"او|أو|ولا",
           "inner": r"(?:^|(?<= ))(?:ما|مش|مو|لا|مافي|مفيش)(?= )"},
    "fa": {"before": r"بدون|هیچ",
           "after": r"[^ ]{0,3} ?(?:(?:فکر|قصد|احساس|اصلا|هیچ) )?(?:ندار|نمی ?کن|نمیکن|نیست|نمی ?کش|نمیکش|نکرد|نمی ?خواه|نمیخوا)"},
    "ur": {"after": r"[^ ]{0,3} ?(?:(?:بھی|بالکل|تو|کوئی|کچھ) )*(?:نہیں|نہ)(?: (?:ہے|ہیں|تھا|تھی|ہو رہا|ہو رہی|ہوتا|ہوتی))?(?= ?(?:$|[,.؟!،۔]|اور |لیکن |پر ))"},
    "hi": {"after": r"[^ ]{0,3} ?(?:(?:भी|बिल्कुल|बिलकुल|तो|जरा|कोई|कुछ) )*(?:नहीं|नही|न|ना)(?: (?:है|हैं|था|थी|थे|हो रहा|हो रही|हो रहे|होता|होती|हुआ|हुई|लग रहा|लग रही))?"
                    r"(?= ?(?:$|[,.।!?]|और |पर |लेकिन |बस ))",
           "inner": r"(?:^|(?<= ))(?:नहीं|नही)(?= |$|,)"},
    "bn": {"after": r"[^ ]{0,3} ?(?:(?:ও|একদম|কোনো|কোন) )*(?:(?:হচ্ছে|করছে|করে|হয়|লাগছে) )?(?:নেই|না|নাই|নয়)(?= ?(?:$|[,.।!?]|আর |কিন্তু ))"},
    "hi_latn": {"before": r"bina|koi nahi",
                "after": r"\w{0,3} ?(?:(?:bhi|bilkul|to|koi|kuch) )*(?:nahi|nahin|nhi|nai)(?: (?:hai|he|tha|thi|ho raha|ho rahi|hota|hoti))?(?= ?(?:$|[,.!?]|aur |par |lekin ))",
                "inner": r"\b(?:nahi|nahin|nhi|nai)\b"},
    "bn_latn": {"after": r"\w{0,3} ?(?:(?:o|ekdom|kono) )*(?:nei|nai|na)(?= ?(?:$|[,.!?]|ar |kintu ))"},
    "fa_latn": {"before": r"bedune|hich", "after": r"\w{0,3} ?(?:(?:fekr|ghasd|hich) )?(?:nadar\w*|nemikon\w*|nist|nemikesh\w*|nemikham)"},
    "ja_latn": {"after": r"\w{0,3} ?(?:wa |ga |mo )?(?:nai|naidesu|arimasen|kunai|shinai|shimasen)\b"},
    "ko_latn": {"after": r"\w{0,3} ?(?:eops|eopseo|anh|ani)"},
    "ar_latn": {"before": r"ma|msh|mish|mesh|mush|mo|mafi|ma fi|mafish|mafeesh|bala|bdun|bidun|la|wala|ma 3andi|ma3andi|ma 3ndi", "fill": r"ay|abadan|aslan|shi|b|fi"},
    "zh_latn": {"before": r"mei you|meiyou|mei|bu|wu|cong lai mei you|bing mei you", "fill": r"you|xiang guo|xiang|yao|hui|ren he|shen me|gan jue|jue de",
                "inner": r"(?<!xiong )\b(?:bu|mei|mei you)\b(?! (?:guo|shang|chu|zhi|ting|xing|neng|qing|sui|dao))"},
    "ru_latn": {"before": r"ne|net|bez|nikakoj|nikakih", "fill": r"u menya|chuvstvuyu|khochu|hochu|sobirayus"},
}
