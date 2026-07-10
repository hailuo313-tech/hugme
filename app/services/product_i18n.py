"""Product copy and keyword packs for all supported languages."""

from __future__ import annotations

from typing import Final, Mapping

from services.emotion_lexicon import (
    SUPPORTED_LANGUAGES,
    detect_language_from_text,
    normalize_language,
)

PRODUCT_LANGUAGE_CODES: Final[tuple[str, ...]] = tuple(sorted(SUPPORTED_LANGUAGES))

_PROFILE_KEYS: Final[frozenset[str]] = frozenset(
    {"country_question", "country_retry", "age_question", "age_retry"}
)


def normalize_product_language(value: str | None, *, default: str = "en") -> str:
    code = normalize_language(value, default=default)
    return code if code in SUPPORTED_LANGUAGES else default


def pick_localized(table: Mapping[str, str], language: str | None, *, default: str = "en") -> str:
    lang = normalize_product_language(language, default=default)
    return str(table.get(lang) or table.get(default) or table["en"])


def _require_language_table(table: Mapping[str, str], *, name: str) -> dict[str, str]:
    missing = SUPPORTED_LANGUAGES - set(table.keys())
    if missing:
        raise ValueError(f"{name} missing languages: {sorted(missing)}")
    return dict(table)


def _require_profile_table(table: Mapping[str, Mapping[str, str]]) -> dict[str, dict[str, str]]:
    missing_langs = SUPPORTED_LANGUAGES - set(table.keys())
    if missing_langs:
        raise ValueError(f"PROFILE_INTAKE_COPY missing languages: {sorted(missing_langs)}")
    for lang, row in table.items():
        missing_keys = _PROFILE_KEYS - set(row.keys())
        if missing_keys:
            raise ValueError(f"PROFILE_INTAKE_COPY[{lang}] missing keys: {sorted(missing_keys)}")
    return {lang: dict(row) for lang, row in table.items()}


# ── Profile intake ───────────────────────────────────────────────────────────

PROFILE_INTAKE_COPY: dict[str, dict[str, str]] = _require_profile_table(
    {
        "en": {
            "country_question": (
                "Before we continue, which country are you in? You can reply with a country name "
                "or code, like US, Canada, Japan, or Germany."
            ),
            "country_retry": (
                "I could not recognize that country. Please reply with your country name or a "
                "two-letter code, like US, GB, JP, or SG."
            ),
            "age_question": "Thanks. How old are you?",
            "age_retry": "Please reply with your age as a number, for example 24.",
        },
        "zh": {
            "country_question": "继续之前，你在哪个国家？可以用国家名或代码回复，比如 US、Canada、Japan、Germany。",
            "country_retry": "我没识别出来。请回复国家名或两位代码，比如 US、GB、JP、SG。",
            "age_question": "谢谢。你多大了？",
            "age_retry": "请用数字回复年龄，比如 24。",
        },
        "es": {
            "country_question": "Antes de seguir, ¿en qué país estás? Puedes responder con el país o el código, como US, Canada, Japan o Germany.",
            "country_retry": "No pude reconocer ese país. Responde con el nombre de tu país o un código de dos letras, como US, GB, JP o SG.",
            "age_question": "Gracias. ¿Cuántos años tienes?",
            "age_retry": "Responde con tu edad en número, por ejemplo 24.",
        },
        "pt": {
            "country_question": "Antes de continuar, em que país você está? Pode responder com o país ou o código, como US, Canada, Japan ou Germany.",
            "country_retry": "Não consegui reconhecer esse país. Responda com o nome do país ou um código de duas letras, como US, GB, JP ou SG.",
            "age_question": "Obrigado. Quantos anos você tem?",
            "age_retry": "Responda com sua idade em número, por exemplo 24.",
        },
        "ja": {
            "country_question": "続ける前に、どの国にいますか？US、Canada、Japan、Germany のように国名かコードで答えてください。",
            "country_retry": "その国を認識できませんでした。US、GB、JP、SG のように国名か2文字コードで答えてください。",
            "age_question": "ありがとう。何歳ですか？",
            "age_retry": "年齢を数字で答えてください。例: 24",
        },
        "ko": {
            "country_question": "계속하기 전에 어느 나라에 있나요? US, Canada, Japan, Germany처럼 나라 이름이나 코드로 답해 주세요.",
            "country_retry": "그 국가는 인식하지 못했어요. US, GB, JP, SG처럼 국가명이나 두 글자 코드로 답해 주세요.",
            "age_question": "고마워요. 몇 살인가요?",
            "age_retry": "나이를 숫자로 답해 주세요. 예: 24",
        },
        "fr": {
            "country_question": "Avant de continuer, dans quel pays es-tu ? Tu peux répondre avec le pays ou un code, comme US, Canada, Japan ou Germany.",
            "country_retry": "Je n'ai pas reconnu ce pays. Réponds avec le nom du pays ou un code à deux lettres, comme US, GB, JP ou SG.",
            "age_question": "Merci. Quel âge as-tu ?",
            "age_retry": "Réponds avec ton âge en chiffres, par exemple 24.",
        },
        "de": {
            "country_question": "Bevor wir weitermachen, in welchem Land bist du? Antworte mit dem Land oder Code, z. B. US, Canada, Japan oder Germany.",
            "country_retry": "Das Land habe ich nicht erkannt. Antworte mit dem Ländernamen oder einem zweistelligen Code, z. B. US, GB, JP oder SG.",
            "age_question": "Danke. Wie alt bist du?",
            "age_retry": "Antworte bitte mit deinem Alter als Zahl, zum Beispiel 24.",
        },
        "it": {
            "country_question": "Prima di continuare, in quale paese sei? Puoi rispondere con il paese o un codice, come US, Canada, Japan o Germany.",
            "country_retry": "Non ho riconosciuto quel paese. Rispondi con il nome del paese o un codice a due lettere, come US, GB, JP o SG.",
            "age_question": "Grazie. Quanti anni hai?",
            "age_retry": "Rispondi con la tua età in numeri, per esempio 24.",
        },
        "nl": {
            "country_question": "Voordat we verdergaan, in welk land ben je? Antwoord met een land of code, zoals US, Canada, Japan of Germany.",
            "country_retry": "Ik herkende dat land niet. Antwoord met je land of een code van twee letters, zoals US, GB, JP of SG.",
            "age_question": "Dank je. Hoe oud ben je?",
            "age_retry": "Antwoord met je leeftijd als getal, bijvoorbeeld 24.",
        },
        "sv": {
            "country_question": "Innan vi fortsätter, vilket land är du i? Svara med land eller kod, som US, Canada, Japan eller Germany.",
            "country_retry": "Jag kände inte igen landet. Svara med landets namn eller en kod på två bokstäver, som US, GB, JP eller SG.",
            "age_question": "Tack. Hur gammal är du?",
            "age_retry": "Svara med din ålder som ett nummer, till exempel 24.",
        },
        "da": {
            "country_question": "Før vi fortsætter, hvilket land er du i? Svar med land eller kode, som US, Canada, Japan eller Germany.",
            "country_retry": "Jeg genkendte ikke landet. Svar med landets navn eller en kode på to bogstaver, som US, GB, JP eller SG.",
            "age_question": "Tak. Hvor gammel er du?",
            "age_retry": "Svar med din alder som et tal, for eksempel 24.",
        },
        "no": {
            "country_question": "Før vi fortsetter, hvilket land er du i? Svar med land eller kode, som US, Canada, Japan eller Germany.",
            "country_retry": "Jeg gjenkjente ikke landet. Svar med landnavn eller en kode på to bokstaver, som US, GB, JP eller SG.",
            "age_question": "Takk. Hvor gammel er du?",
            "age_retry": "Svar med alderen din som et tall, for eksempel 24.",
        },
        "fi": {
            "country_question": "Ennen kuin jatkamme, missä maassa olet? Voit vastata maalla tai koodilla, kuten US, Canada, Japan tai Germany.",
            "country_retry": "En tunnistanut maata. Vastaa maan nimellä tai kahden kirjaimen koodilla, kuten US, GB, JP tai SG.",
            "age_question": "Kiitos. Kuinka vanha olet?",
            "age_retry": "Vastaa iälläsi numeroina, esimerkiksi 24.",
        },
        "is": {
            "country_question": "Áður en við höldum áfram, í hvaða landi ertu? Þú getur svarað með landi eða kóða, eins og US, Canada, Japan eða Germany.",
            "country_retry": "Ég þekkti ekki landið. Svaraðu með nafni lands eða tveggja stafa kóða, eins og US, GB, JP eða SG.",
            "age_question": "Takk. Hve old ertu?",
            "age_retry": "Svaraðu með aldri sem tölu, til dæmis 24.",
        },
        "el": {
            "country_question": "Πριν συνεχίσουμε, σε ποια χώρα είσαι; Μπορείς να απαντήσεις με χώρα ή κωδικό, όπως US, Canada, Japan ή Germany.",
            "country_retry": "Δεν αναγνώρισα τη χώρα. Απάντησε με όνομα χώρας ή δύο γράμματα, όπως US, GB, JP ή SG.",
            "age_question": "Ευχαριστώ. Πόσων χρονών είσαι;",
            "age_retry": "Απάντησε με την ηλικία σου σε αριθμούς, π.χ. 24.",
        },
        "cs": {
            "country_question": "Než budeme pokračovat, ve které zemi jsi? Odpověz názvem země nebo kódem, například US, Canada, Japan nebo Germany.",
            "country_retry": "Tu zemi jsem nepoznal. Odpověz názvem země nebo dvoupísmenným kódem, například US, GB, JP nebo SG.",
            "age_question": "Díky. Kolik ti je let?",
            "age_retry": "Odpověz věkem jako číslem, například 24.",
        },
    }
)


def profile_intake_text(kind: str, language: str | None, *, user_text: str | None = None) -> str:
    lang = normalize_product_language(
        language or detect_language_from_text(user_text or "", default="en"),
        default="en",
    )
    row = PROFILE_INTAKE_COPY.get(lang) or PROFILE_INTAKE_COPY["en"]
    return row.get(kind) or PROFILE_INTAKE_COPY["en"][kind]


# ── Nurture inbound-call guidance ────────────────────────────────────────────

NURTURE_NEED_HELP_COPY: dict[str, str] = _require_language_table(
    {
        "en": "Tap the video call button on my profile to call me — I'll pick up.",
        "zh": "点我资料页顶部的视频通话按钮打过来，我会接的。",
        "es": "Toca el botón de videollamada en mi perfil para llamarme — te contesto.",
        "pt": "Toque no botão de chamada de vídeo no meu perfil para me ligar — eu atendo.",
        "ja": "プロフィールのビデオ通話ボタンをタップしてかけてね — 出るよ。",
        "ko": "내 프로필의 영상통화 버튼을 눌러 전화해 — 받을게.",
        "fr": "Appuie sur le bouton d'appel vidéo de mon profil pour m'appeler — je réponds.",
        "de": "Tippe auf die Videoanruf-Schaltfläche in meinem Profil — ich gehe ran.",
        "it": "Tocca il pulsante videochiamata sul mio profilo per chiamarmi — rispondo subito.",
        "nl": "Tik op de videogesprek-knop op mijn profiel om me te bellen — ik neem op.",
        "sv": "Tryck på videosamtalsknappen på min profil för att ringa mig — jag svarar.",
        "da": "Tryk på videoopkald-knappen på min profil for at ringe til mig — jeg tager den.",
        "no": "Trykk på videosamtale-knappen på profilen min for å ringe meg — jeg svarer.",
        "fi": "Napauta profiilini videopuhelupainiketta soittaaksesi minulle — vastaan.",
        "is": "Ýttu á myndsímtalshnappinn á prófílnum mínum til að hringja — ég svara.",
        "el": "Πάτα το κουμπί βιντεοκλήσης στο προφίλ μου για να μου τηλεφωνήσεις — θα απαντήσω.",
        "cs": "Klepni na tlačítko videohovoru v mém profilu a zavolej mi — zvednu to.",
    },
    name="NURTURE_NEED_HELP_COPY",
)

NURTURE_ACCEPT_ACK_COPY: dict[str, str] = _require_language_table(
    {
        "en": "Perfect — tap call on my profile now and I'll pick up right away.",
        "zh": "好，现在点我资料页的视频通话打过来，我马上接。",
        "es": "Perfecto — toca videollamada en mi perfil ahora y te contesto enseguida.",
        "pt": "Perfeito — toca em chamada no meu perfil agora que eu atendo na hora.",
        "ja": "いいね — 今すぐプロフィールの通話をタップして。すぐ出るよ。",
        "ko": "좋아 — 지금 프로필에서 통화 눌러줘. 바로 받을게.",
        "fr": "Parfait — appuie sur appel vidéo sur mon profil maintenant, je réponds tout de suite.",
        "de": "Perfekt — tippe jetzt auf Anruf in meinem Profil, ich gehe sofort ran.",
        "it": "Perfetto — tocca videochiamata sul mio profilo adesso e rispondo subito.",
        "nl": "Perfect — tik nu op bellen op mijn profiel, ik neem meteen op.",
        "sv": "Perfekt — tryck på samtal på min profil nu så svarar jag direkt.",
        "da": "Perfekt — tryk på opkald på min profil nu, så tager jeg den med det samme.",
        "no": "Perfekt — trykk på anrop på profilen min nå, så svarer jeg med en gang.",
        "fi": "Hyvä — napauta profiilini puhelua nyt, vastaan heti.",
        "is": "Frábært — ýttu á símtal á prófílnum mínum núna og ég svara strax.",
        "el": "Τέλεια — πάτα κλήση στο προφίλ μου τώρα και θα απαντήσω αμέσως.",
        "cs": "Skvělé — klepni teď na hovor v mém profilu a hned to zvednu.",
    },
    name="NURTURE_ACCEPT_ACK_COPY",
)

NURTURE_DELAY_FOLLOWUP_COPY: dict[str, str] = _require_language_table(
    {
        "en": "No rush — tap call on my profile whenever you're free for a quick video.",
        "zh": "不急，你有空就点我资料页的视频打过来。",
        "es": "Sin prisa — toca videollamada en mi perfil cuando estés libre.",
        "pt": "Sem pressa — toque em chamada no meu perfil quando estiver livre.",
        "ja": "急がなくていいよ — 暇なときにプロフィールからビデオ通話してね。",
        "ko": "서두르지 않아도 돼 — 시간 될 때 프로필에서 영상통화 눌러줘.",
        "fr": "Pas de rush — appuie sur appel vidéo sur mon profil quand tu es libre.",
        "de": "Kein Stress — tippe auf Anruf in meinem Profil, wenn du Zeit für ein kurzes Video hast.",
        "it": "Nessuna fretta — tocca videochiamata sul mio profilo quando sei libero.",
        "nl": "Geen haast — tik op bellen op mijn profiel wanneer je tijd hebt.",
        "sv": "Ingen brådska — tryck på samtal på min profil när du har tid.",
        "da": "Ingen stress — tryk på opkald på min profil når du har tid.",
        "no": "Ingen stress — trykk på anrop på profilen min når du har tid.",
        "fi": "Ei kiirettä — napauta profiilini puhelua kun ehdit.",
        "is": "Engin pressa — ýttu á símtal á prófílnum mínum þegar þú hefur tíma.",
        "el": "Χωρίς βιασύνη — πάτα κλήση στο προφίλ μου όταν είσαι ελεύθερος.",
        "cs": "Bez spěchu — klepni na hovor v mém profilu, až budeš mít čas.",
    },
    name="NURTURE_DELAY_FOLLOWUP_COPY",
)

NURTURE_VIDEO_ROUND_COPY: dict[int, dict[str, str]] = {
    1: _require_language_table(
        {
            "en": "Still here? Tap call on my profile for a quick video.",
            "zh": "我还在呢，点我资料页的视频通话打过来，聊一小会儿？",
            "es": "Sigo aquí. Toca videollamada en mi perfil si quieres hablar ahora.",
            "pt": "Ainda estou aqui. Toca em chamada de vídeo no meu perfil se quiser conversar.",
            "ja": "まだここにいるよ。プロフィールからビデオ通話してくれたら話そう。",
            "ko": "아직 여기 있어. 프로필에서 영상통화 눌러줄래?",
            "fr": "Toujours là ? Appuie sur appel vidéo sur mon profil pour un petit appel.",
            "de": "Noch da? Tippe auf Anruf in meinem Profil für ein kurzes Video.",
            "it": "Sono ancora qui. Tocca videochiamata sul mio profilo se vuoi parlare.",
            "nl": "Nog steeds hier? Tik op bellen op mijn profiel voor een kort videogesprek.",
            "sv": "Fortfarande här? Tryck på samtal på min profil för ett snabbt videosamtal.",
            "da": "Stadig her? Tryk på opkald på min profil for en hurtig video.",
            "no": "Fortsatt her? Trykk på anrop på profilen min for en rask video.",
            "fi": "Yhä täällä? Napauta profiilini puhelua nopeaan videoon.",
            "is": "Enn hér? Ýttu á símtal á prófílnum mínum fyrir stutta myndsímtal.",
            "el": "Ακόμα εδώ; Πάτα κλήση στο προφίλ μου για γρήγορο βίντεο.",
            "cs": "Pořád tu jsem? Klepni na hovor v mém profilu na rychlé video.",
        },
        name="NURTURE_VIDEO_ROUND_COPY[1]",
    ),
    2: _require_language_table(
        {
            "en": "I was waiting for you. Tap call on my profile — I'll pick up.",
            "zh": "我刚刚还在等你，点我资料页的视频通话打过来，我会接。",
            "es": "Te estaba esperando. Toca videollamada en mi perfil y te contesto.",
            "pt": "Eu estava te esperando. Toca na chamada do meu perfil que eu atendo.",
            "ja": "待ってたよ。プロフィールから通話して — 出るから。",
            "ko": "널 기다리고 있었어. 프로필에서 통화 눌러 — 받을게.",
            "fr": "Je t'attendais. Appuie sur appel vidéo sur mon profil — je réponds.",
            "de": "Ich habe auf dich gewartet. Tippe auf Anruf in meinem Profil — ich gehe ran.",
            "it": "Ti stavo aspettando. Tocca videochiamata sul mio profilo — rispondo.",
            "nl": "Ik wachtte op je. Tik op bellen op mijn profiel — ik neem op.",
            "sv": "Jag väntade på dig. Tryck på samtal på min profil — jag svarar.",
            "da": "Jeg ventede på dig. Tryk på opkald på min profil — jeg tager den.",
            "no": "Jeg ventet på deg. Trykk på anrop på profilen min — jeg svarer.",
            "fi": "Odotin sinua. Napauta profiilini puhelua — vastaan.",
            "is": "Ég beið eftir þér. Ýttu á símtal á prófílnum mínum — ég svara.",
            "el": "Σε περίμενα. Πάτα κλήση στο προφίλ μου — θα απαντήσω.",
            "cs": "Čekal jsem na tebe. Klepni na hovor v mém profilu — zvednu to.",
        },
        name="NURTURE_VIDEO_ROUND_COPY[2]",
    ),
    3: _require_language_table(
        {
            "en": "I liked talking with you yesterday. Tap call on my profile tonight if you're free.",
            "zh": "昨天聊得挺开心，今晚有空就点我资料页的视频打过来。",
            "es": "Me gustó hablar contigo ayer. Esta noche toca videollamada en mi perfil si puedes.",
            "pt": "Gostei de falar com você ontem. Hoje à noite toca em chamada no meu perfil se puder.",
            "ja": "昨日話せて楽しかった。今夜暇ならプロフィールからビデオ通話してね。",
            "ko": "어제 이야기해서 좋았어. 오늘 밤 시간 되면 프로필에서 통화 눌러줘.",
            "fr": "J'ai aimé parler avec toi hier. Ce soir, appuie sur appel vidéo sur mon profil si tu es libre.",
            "de": "Gestern hat mir unser Chat gefallen. Heute Abend tippe auf Anruf in meinem Profil, wenn du Zeit hast.",
            "it": "Mi è piaciuto parlare con te ieri. Stasera tocca videochiamata sul mio profilo se puoi.",
            "nl": "Leuk gepraat gisteren. Vanavond tik op bellen op mijn profiel als je tijd hebt.",
            "sv": "Det var nice att prata igår. I kväll, tryck på samtal på min profil om du har tid.",
            "da": "Det var dejligt at snakke i går. I aften, tryk på opkald på min profil hvis du har tid.",
            "no": "Koselig å prate i går. I kveld, trykk på anrop på profilen min hvis du har tid.",
            "fi": "Oli kiva jutella eilen. Tänä iltana napauta profiilini puhelua jos ehdit.",
            "is": "Gamansamt að spjalla í gær. Í kvöld, ýttu á símtal á prófílnum mínum ef þú hefur tíma.",
            "el": "Μου άρεσε να μιλάμε χθες. Απόψε, πάτα κλήση στο προφίλ μου αν είσαι ελεύθερος.",
            "cs": "Včera se mi s tebou hezky povídalo. Dnes večer klepni na hovor v mém profilu, pokud můžeš.",
        },
        name="NURTURE_VIDEO_ROUND_COPY[3]",
    ),
}


def nurture_video_round_text(round_num: int, language: str | None) -> str:
    table = NURTURE_VIDEO_ROUND_COPY.get(round_num) or NURTURE_VIDEO_ROUND_COPY[1]
    return pick_localized(table, language)


# ── Refusal replacement flirt fallback ───────────────────────────────────────

FLIRT_FALLBACK_COPY: dict[str, str] = _require_language_table(
    {
        "en": "Mmm you already have my attention. Tell me exactly what you want.",
        "zh": "嗯，你已经引起我的注意了。告诉我你到底想要什么。",
        "es": "Me estás provocando. Dime exactamente qué quieres que haga contigo.",
        "pt": "Você está me deixando com vontade. Me diz exatamente o que quer sentir.",
        "ja": "うん、もう気になってる。欲しいことをはっきり教えて。",
        "ko": "음, 벌써 눈에 들어왔어. 정확히 뭘 원하는지 말해줘.",
        "fr": "Mmm tu as déjà mon attention. Dis-moi exactement ce que tu veux.",
        "de": "Mmm, du hast schon meine Aufmerksamkeit. Sag mir genau, was du willst.",
        "it": "Mi stai accendendo. Dimmi esattamente cosa vuoi che ti faccia sentire.",
        "nl": "Mmm je hebt al mijn aandacht. Vertel me precies wat je wilt.",
        "sv": "Mmm du har redan min uppmärksamhet. Säg exakt vad du vill ha.",
        "da": "Mmm du har allerede min opmærksomhed. Fortæl mig præcis hvad du vil have.",
        "no": "Mmm du har allerede oppmerksomheten min. Si nøyaktig hva du vil ha.",
        "fi": "Mmm sinulla on jo huomioni. Kerro tarkalleen mitä haluat.",
        "is": "Mmm þú hefur þegar athygli mína. Segðu mér nákvæmlega hvað þú vilt.",
        "el": "Μμμ, ήδη τράβηξες την προσοχή μου. Πες μου ακριβώς τι θέλεις.",
        "cs": "Mmm, už máš mou pozornost. Řekni mi přesně, co chceš.",
    },
    name="FLIRT_FALLBACK_COPY",
)


# ── Asset / video keywords (merged across 17 languages) ──────────────────────

_ASSET_IMAGE_BY_LANG: dict[str, tuple[str, ...]] = {
    "en": (
        "photo", "photos", "pic", "pics", "picture", "pictures", "selfie", "selfies",
        "image", "images", "snapshot", "snap", "face pic", "body pic", "full body",
        "mirror selfie", "your face", "your body", "nudes", "nude",
    ),
    "zh": ("照片", "图片", "自拍", "裸体", "裸照", "大奶", "奶子"),
    "es": (
        "foto", "fotos", "imagen", "imagenes", "imágenes", "retrato", "selfi",
        "desnudo", "desnuda", "desnudos", "foto tuya", "foto en escote",
    ),
    "pt": ("foto", "fotos", "imagem", "imagens", "foto sua", "fotos suas", "nude", "nua"),
    "ja": ("写真", "画像", "自撮り", "ヌード", "裸"),
    "ko": ("사진", "이미지", "셀카", "누드", "나체"),
    "fr": ("photo", "photos", "image", "images", "selfie", "nu", "nue", "nus"),
    "de": ("foto", "fotos", "bild", "bilder", "selfie", "nackt", "nacktfoto"),
    "it": ("foto", "immagine", "immagini", "selfie", "nudo", "nuda"),
    "nl": ("foto", "fotos", "afbeelding", "selfie", "naakt"),
    "sv": ("foto", "bild", "bilder", "selfie", "naken"),
    "da": ("foto", "billede", "billeder", "selfie", "nøgen"),
    "no": ("foto", "bilde", "bilder", "selfie", "naken"),
    "fi": ("kuva", "kuvat", "selfie", "alaston", "alastonkuva"),
    "is": ("mynd", "myndir", "selfie", "nakinn", "nakin"),
    "el": ("φωτογραφία", "φωτο", "εικόνα", "selfie", "γυμνό", "γυμνή"),
    "cs": ("foto", "fotka", "fotky", "obrázek", "selfie", "nahý", "nahá"),
}

_ASSET_VIDEO_BY_LANG: dict[str, tuple[str, ...]] = {
    "en": (
        "video", "videos", "vid", "vids", "clip", "clips", "movie", "gif", "tape",
        "recording", "custom video", "dirty video", "short clip", "private video", "bedroom video",
    ),
    "zh": ("视频", "小视频", "录像", "短片"),
    "es": ("video", "videos", "videito", "clip", "clips", "grabación", "video privado"),
    "pt": ("vídeo", "video", "videos", "clip", "clips", "gravação", "video privado"),
    "ja": ("動画", "ビデオ", "クリップ", "録画"),
    "ko": ("영상", "비디오", "동영상", "클립", "녹화"),
    "fr": ("vidéo", "video", "videos", "clip", "clips", "enregistrement"),
    "de": ("video", "videos", "clip", "clips", "aufnahme", "filmchen"),
    "it": ("video", "videos", "clip", "clips", "registrazione"),
    "nl": ("video", "videos", "clip", "clips", "opname"),
    "sv": ("video", "videos", "klipp", "inspelning"),
    "da": ("video", "videos", "klip", "optagelse"),
    "no": ("video", "videos", "klipp", "opptak"),
    "fi": ("video", "videot", "klippi", "tallenne"),
    "is": ("myndband", "myndbönd", "klipp", "upptaka"),
    "el": ("βίντεο", "βιντεο", "κλιπ", "εγγραφή"),
    "cs": ("video", "videa", "klip", "klipy", "nahrávka"),
}

_ASSET_REQUEST_BY_LANG: dict[str, tuple[str, ...]] = {
    "en": (
        "send", "show", "see", "watch", "look", "view", "share", "drop", "give", "upload",
        "want", "wanna", "need", "can i", "could i", "may i", "let me", "lemme", "please",
        "pls", "have", "got", "any", "do you have", "you have",
    ),
    "zh": ("想", "想看", "想要", "要", "看", "发", "有", "有没有", "给我", "发来"),
    "es": (
        "mándame", "mandame", "envíame", "enviame", "muéstrame", "muestrame", "muestra",
        "dame", "crea", "crear", "manda", "envia", "envía", "quiero ver", "puedo ver",
    ),
    "pt": (
        "me manda", "me mande", "me envia", "me envie", "mostra", "mostre", "quero ver",
        "pode mandar", "manda", "envia",
    ),
    "ja": ("送って", "見せて", "見たい", "欲しい", "ちょうだい", "くれ"),
    "ko": ("보내", "보여", "보고 싶", "줘", "원해", "보내줘"),
    "fr": ("envoie", "envoyez", "montre", "montrez", "je veux voir", "donne", "donnez"),
    "de": ("schick", "schick mir", "zeig", "zeige", "ich will sehen", "gib mir", "sende"),
    "it": ("mandami", "invia", "mostrami", "voglio vedere", "dammi", "manda"),
    "nl": ("stuur", "stuur me", "laat zien", "ik wil zien", "geef me"),
    "sv": ("skicka", "visa", "jag vill se", "ge mig", "skicka mig"),
    "da": ("send", "vis", "jeg vil se", "giv mig", "send mig"),
    "no": ("send", "vis", "jeg vil se", "gi meg", "send meg"),
    "fi": ("lähetä", "näytä", "haluan nähdä", "anna minulle"),
    "is": ("sendu", "sýndu", "ég vil sjá", "gefðu mér"),
    "el": ("στείλε", "δείξε", "θέλω να δω", "δώσε μου"),
    "cs": ("pošli", "ukaž", "chci vidět", "dej mi", "pošli mi"),
}

_VIDEO_CALL_BY_LANG: dict[str, tuple[str, ...]] = {
    "en": (
        "video call", "videocall", "facetime", "face time", "cam2cam", "c2c",
        "live show", "private call", "call me", "video chat",
    ),
    "zh": ("视频通话", "视频电话", "打视频", "开视频", "视讯", "裸聊"),
    "es": ("videollamada", "videollamadas", "llamada de video", "llamada por video", "videollamada conmigo"),
    "pt": ("chamada de video", "chamada de vídeo", "videochamada", "ligação de vídeo"),
    "ja": ("ビデオ通話", "ビデオチャット", "ビデオ電話", "通話して"),
    "ko": ("영상통화", "화상통화", "영상 채팅", "영상전화"),
    "fr": ("appel vidéo", "appel video", "facetime", "visio", "visiochat"),
    "de": ("videoanruf", "video anruf", "facetime", "video chat"),
    "it": ("videochiamata", "chiamata video", "facetime", "video chat"),
    "nl": ("videogesprek", "video bellen", "facetime", "videochat"),
    "sv": ("videosamtal", "videosamtal", "facetime", "videochatt"),
    "da": ("videoopkald", "video opkald", "facetime", "videochat"),
    "no": ("videosamtale", "video samtale", "facetime", "videochat"),
    "fi": ("videopuhelu", "video puhelu", "facetime", "videochat"),
    "is": ("myndsímtal", "myndsamtal", "facetime", "myndspjall"),
    "el": ("βιντεοκλήση", "βιντεο κλήση", "facetime", "video chat"),
    "cs": ("videohovor", "video hovor", "facetime", "video chat"),
}


def _merge_keyword_packs(packs: Mapping[str, tuple[str, ...]]) -> tuple[str, ...]:
    seen: set[str] = set()
    merged: list[str] = []
    for lang in PRODUCT_LANGUAGE_CODES:
        for keyword in packs.get(lang, ()):
            key = keyword.casefold().strip()
            if key and key not in seen:
                seen.add(key)
                merged.append(keyword)
    return tuple(merged)


ASSET_IMAGE_KEYWORDS: tuple[str, ...] = _merge_keyword_packs(_ASSET_IMAGE_BY_LANG)
ASSET_VIDEO_KEYWORDS: tuple[str, ...] = _merge_keyword_packs(_ASSET_VIDEO_BY_LANG)
ASSET_REQUEST_TERMS: tuple[str, ...] = _merge_keyword_packs(_ASSET_REQUEST_BY_LANG)
VIDEO_CALL_KEYWORDS: tuple[str, ...] = _merge_keyword_packs(_VIDEO_CALL_BY_LANG)
UNICODE_VIDEO_CALL_KEYWORDS: tuple[str, ...] = tuple(
    token for token in VIDEO_CALL_KEYWORDS if not token.isascii()
)
