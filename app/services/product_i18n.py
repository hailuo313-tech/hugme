"""Product copy and keyword packs for all supported languages."""

from __future__ import annotations

import re
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


# The profile flow asks for city when country cannot be inferred.  Internal key
# names stay compatible with existing pending-profile records.
_CITY_INTAKE_COPY: dict[str, tuple[str, str]] = {
    "en": ("Before we continue, which city are you in? I'll use it to identify your country.", "I couldn't identify that city. Which city are you in?"),
    "zh": ("继续之前，你在哪个城市？我会根据城市判断你的国家。", "我没识别出这个城市。请告诉我你所在的城市。"),
    "es": ("Antes de seguir, ¿en qué ciudad estás? La usaré para identificar tu país.", "No pude identificar esa ciudad. ¿En qué ciudad estás?"),
    "pt": ("Antes de continuar, em que cidade você está? Vou usá-la para identificar seu país.", "Não consegui identificar essa cidade. Em que cidade você está?"),
    "ja": ("続ける前に、どの都市にいますか？都市から国を確認します。", "その都市を特定できませんでした。今いる都市を教えてください。"),
    "ko": ("계속하기 전에 어느 도시에 있나요? 도시를 바탕으로 국가를 확인할게요.", "그 도시를 확인하지 못했어요. 어느 도시에 있나요?"),
    "fr": ("Avant de continuer, dans quelle ville es-tu ? Je l'utiliserai pour identifier ton pays.", "Je n'ai pas pu identifier cette ville. Dans quelle ville es-tu ?"),
    "de": ("Bevor wir weitermachen, in welcher Stadt bist du? Daraus bestimme ich dein Land.", "Ich konnte diese Stadt nicht zuordnen. In welcher Stadt bist du?"),
    "it": ("Prima di continuare, in quale città sei? La userò per identificare il tuo paese.", "Non sono riuscita a identificare quella città. In quale città sei?"),
    "nl": ("Voordat we verdergaan, in welke stad ben je? Daarmee bepaal ik je land.", "Ik kon die stad niet herkennen. In welke stad ben je?"),
    "sv": ("Innan vi fortsätter, vilken stad är du i? Jag använder den för att hitta ditt land.", "Jag kunde inte identifiera staden. Vilken stad är du i?"),
    "da": ("Før vi fortsætter, hvilken by er du i? Jeg bruger den til at finde dit land.", "Jeg kunne ikke identificere byen. Hvilken by er du i?"),
    "no": ("Før vi fortsetter, hvilken by er du i? Jeg bruker den til å finne landet ditt.", "Jeg kunne ikke identifisere byen. Hvilken by er du i?"),
    "fi": ("Ennen kuin jatkamme, missä kaupungissa olet? Selvitän sen avulla maasi.", "En tunnistanut kaupunkia. Missä kaupungissa olet?"),
    "is": ("Áður en við höldum áfram, í hvaða borg ertu? Ég nota hana til að finna landið þitt.", "Ég gat ekki fundið borgina. Í hvaða borg ertu?"),
    "el": ("Πριν συνεχίσουμε, σε ποια πόλη είσαι; Θα τη χρησιμοποιήσω για να βρω τη χώρα σου.", "Δεν μπόρεσα να αναγνωρίσω την πόλη. Σε ποια πόλη είσαι;"),
    "cs": ("Než budeme pokračovat, ve kterém městě jsi? Podle něj určím tvoji zemi.", "Město se mi nepodařilo rozpoznat. Ve kterém městě jsi?"),
}
for _lang, (_question, _retry) in _CITY_INTAKE_COPY.items():
    PROFILE_INTAKE_COPY[_lang]["country_question"] = _question
    PROFILE_INTAKE_COPY[_lang]["country_retry"] = _retry


def profile_intake_text(kind: str, language: str | None, *, user_text: str | None = None) -> str:
    lang = normalize_product_language(
        language or detect_language_from_text(user_text or "", default="en"),
        default="en",
    )
    row = PROFILE_INTAKE_COPY.get(lang) or PROFILE_INTAKE_COPY["en"]
    return row.get(kind) or PROFILE_INTAKE_COPY["en"][kind]


# ── App-link copy shared by AI replies and Telegram HTML rendering ─────────

APP_LINK_NUDGE_COPY: dict[str, str] = _require_language_table(
    {
        "en": "Chat faster with me in my app: {url} (code: c5a8we)",
        "zh": "在我的 App 里聊更方便：{url}（代码：c5a8we）",
        "es": "Hablemos más rápido en mi app: {url} (código: c5a8we)",
        "pt": "Vamos conversar melhor no meu app: {url} (código: c5a8we)",
        "ja": "私のアプリでもっと気軽に話そう：{url}（コード：c5a8we）",
        "ko": "내 앱에서 더 편하게 이야기해요: {url} (코드: c5a8we)",
        "fr": "Discutons plus facilement dans mon application : {url} (code : c5a8we)",
        "de": "In meiner App können wir einfacher chatten: {url} (Code: c5a8we)",
        "it": "Parliamo più comodamente nella mia app: {url} (codice: c5a8we)",
        "nl": "Praat makkelijker met me in mijn app: {url} (code: c5a8we)",
        "sv": "Prata enklare med mig i min app: {url} (kod: c5a8we)",
        "da": "Tal nemmere med mig i min app: {url} (kode: c5a8we)",
        "no": "Snakk enklere med meg i appen min: {url} (kode: c5a8we)",
        "fi": "Jutellaan helpommin sovelluksessani: {url} (koodi: c5a8we)",
        "is": "Spjöllum auðveldlega í appinu mínu: {url} (kóði: c5a8we)",
        "el": "Ας μιλήσουμε πιο εύκολα στην εφαρμογή μου: {url} (κωδικός: c5a8we)",
        "cs": "Povídejme si pohodlněji v mé aplikaci: {url} (kód: c5a8we)",
    },
    name="APP_LINK_NUDGE_COPY",
)

TRACKING_CTA_COPY: dict[str, str] = _require_language_table(
    {
        "en": "OPEN APP LINK - TAP HERE",
        "zh": "打开 APP 链接 - 点这里",
        "es": "ABRIR ENLACE DE LA APP - TOCA AQUÍ",
        "pt": "ABRIR LINK DO APP - TOQUE AQUI",
        "ja": "アプリのリンクを開く - ここをタップ",
        "ko": "앱 링크 열기 - 여기를 탭하세요",
        "fr": "OUVRIR LE LIEN DE L’APP - APPUIE ICI",
        "de": "APP-LINK ÖFFNEN - HIER TIPPEN",
        "it": "APRI IL LINK DELL’APP - TOCCA QUI",
        "nl": "APP-LINK OPENEN - TIK HIER",
        "sv": "ÖPPNA APP-LÄNKEN - TRYCK HÄR",
        "da": "ÅBN APP-LINKET - TRYK HER",
        "no": "ÅPNE APP-LENKEN - TRYKK HER",
        "fi": "AVAA SOVELLUSLINKKI - NAPAUTA TÄSTÄ",
        "is": "OPNA APPTENGIL - ÝTTU HÉR",
        "el": "ΑΝΟΙΓΜΑ ΣΥΝΔΕΣΜΟΥ ΕΦΑΡΜΟΓΗΣ - ΠΑΤΗΣΕ ΕΔΩ",
        "cs": "OTEVŘÍT ODKAZ APLIKACE - KLEPNI SEM",
    },
    name="TRACKING_CTA_COPY",
)


def app_link_nudge_text(url: str, language: str | None, *, user_text: str | None = None) -> str:
    lang = normalize_product_language(
        language or detect_language_from_text(user_text or "", default="en"),
        default="en",
    )
    return pick_localized(APP_LINK_NUDGE_COPY, lang).format(url=url)


def tracking_cta_label(language: str | None, *, user_text: str | None = None) -> str:
    lang = normalize_product_language(
        language or detect_language_from_text(user_text or "", default="en"),
        default="en",
    )
    return pick_localized(TRACKING_CTA_COPY, lang)


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


# ── In-person meetup: never refuse, softly defer ─────────────────────────────

MEETUP_DEFER_COPY: dict[str, str] = _require_language_table(
    {
        "en": "We'll meet when we know each other better — once we're really friends.",
        "zh": "等我们再熟悉一些、真正成了朋友，我们会见面的。",
        "es": "Cuando nos conozcamos mejor y seamos amigos, nos veremos.",
        "pt": "Quando a gente se conhecer melhor e for amigo de verdade, a gente se encontra.",
        "ja": "もっと仲良くなって、本当の友達になったら会おうね。",
        "ko": "더 친해지고 진짜 친구가 되면 만나자.",
        "fr": "On se verra quand on se connaîtra mieux, une fois qu'on sera vraiment amis.",
        "de": "Wir treffen uns, wenn wir uns besser kennen — wenn wir wirklich Freunde sind.",
        "it": "Ci vedremo quando ci conosceremo meglio, quando saremo davvero amici.",
        "nl": "We zien elkaar als we elkaar beter kennen — als we echt vrienden zijn.",
        "sv": "Vi ses när vi känner varandra bättre — när vi är riktiga vänner.",
        "da": "Vi ses når vi kender hinanden bedre — når vi er rigtige venner.",
        "no": "Vi møtes når vi kjenner hverandre bedre — når vi er ekte venner.",
        "fi": "Tapaamme kun tunnemme toisemme paremmin — kun olemme oikeasti ystäviä.",
        "is": "Við hittumst þegar við þekkjumst betur — þegar við erum alvöru vinir.",
        "el": "Θα βρεθούμε όταν γνωριστούμε καλύτερα — όταν γίνουμε πραγματικοί φίλοι.",
        "cs": "Sejdeme se, až se budeme znát líp — až budeme opravdu kamarádi.",
    },
    name="MEETUP_DEFER_COPY",
)

_GREETING_MEET_RE = re.compile(
    r"(?:"
    r"\b(?:nice|pleased|glad|good|great|lovely|happy) to meet you\b|"
    r"\bmeet(?:ing)? you (?:too|as well)\b|"
    r"认识你很高兴|很高兴认识|幸会"
    r")",
    re.IGNORECASE | re.UNICODE,
)

_VIDEO_MEET_RE = re.compile(
    r"(?:"
    r"\b(?:video call|videocall|facetime|face time|video chat|videochat|"
    r"cam2cam|c2c|videollamada|videochamada|chamada de v[ií]deo)\b|"
    r"视频见面|视频见|打视频|开视频|视频通话|视频电话|"
    r"ビデオ通話|영상통화|화상통화"
    r")",
    re.IGNORECASE | re.UNICODE,
)

_IN_PERSON_MEETUP_RE = re.compile(
    r"(?:"
    r"\b(?:let(?:'s| us)|wanna|want to|wanna go|can we|can i|could we|could i|shall we|we should) "
    r"(?:meet(?:\s+up)?|hang out)\b|"
    r"\b(?:meet(?:\s+up)?|hang out) (?:in person|irl|offline|for real|for coffee|"
    r"for a drink|sometime|together|with me)\b|"
    r"\bmeet (?:up|me|you|in person|irl|offline)\b|"
    r"\b(?:see you|see me) (?:in person|irl|offline|for real)\b|"
    r"\b(?:come over|come see me|visit me|when can we meet)\b|"
    r"见面|见一面|见个面|出来见|出来玩|约出来|当面见|线下见|想见你|想见一面|"
    r"\b(?:vernos|encontrarnos|conocernos en persona|salir juntos)\b|"
    r"\b(?:nos encontrar|te conhecer pessoalmente|sair juntos)\b|"
    r"会いたい|会おう|会える|"
    r"만나자|만나고"
    r")",
    re.IGNORECASE | re.UNICODE,
)


def is_in_person_meetup_request(user_text: str | None) -> bool:
    """True when the user is asking to meet offline — not a video call or greeting."""
    text = " ".join(str(user_text or "").casefold().replace("'", "'").split())
    if not text or _GREETING_MEET_RE.search(text) or _VIDEO_MEET_RE.search(text):
        return False
    if is_outbound_call_request(text) or is_inbound_call_help_request(text):
        return False
    return bool(_IN_PERSON_MEETUP_RE.search(text))


def meetup_defer_reply(
    user_text: str | None = None,
    *,
    language: str | None = None,
) -> str:
    """Warm deferral: we will meet later, after we know each other."""
    lang = normalize_product_language(
        language or detect_language_from_text(user_text or "", default="en"),
        default="en",
    )
    return pick_localized(MEETUP_DEFER_COPY, lang)


# ── Asset / video keywords (merged across 17 languages) ──────────────────────

_ASSET_IMAGE_BY_LANG: dict[str, tuple[str, ...]] = {
    "en": (
        "photo", "photos", "pic", "pics", "picture", "pictures", "selfie", "selfies",
        "image", "images", "snapshot", "snap", "face pic", "body pic", "full body",
        "mirror selfie", "your face", "your body", "nudes", "nude",
    ),
    "zh": (
        "照片", "相片", "图片", "图", "自拍", "自拍照", "截图", "脸照", "全身照",
        "身体照", "镜子自拍", "你的脸", "你的身体", "裸体", "裸照", "大奶", "奶子",
    ),
    "es": (
        "foto", "fotos", "imagen", "imagenes", "imágenes", "retrato", "selfi",
        "selfie", "selfies", "captura", "snap", "foto de cara", "foto del cuerpo",
        "cuerpo completo", "selfie en el espejo", "tu cara", "tu cuerpo", "desnudo",
        "desnuda", "desnudos", "foto tuya", "fotos tuyas", "una foto",
        "foto en escote", "quiero verte", "te quiero ver",
    ),
    "pt": (
        "foto", "fotos", "imagem", "imagens", "selfie", "selfies", "captura",
        "print", "foto do rosto", "foto do corpo", "corpo inteiro", "selfie no espelho",
        "seu rosto", "seu corpo", "foto sua", "fotos suas", "nude", "nua", "nu",
    ),
    "ja": (
        "写真", "画像", "写メ", "自撮り", "セルフィー", "スクショ", "顔写真", "全身写真",
        "体の写真", "鏡自拍", "ミラーセルフィー", "あなたの顔", "あなたの体", "ヌード", "裸",
    ),
    "ko": (
        "사진", "이미지", "셀카", "셀피", "스냅", "캡처", "얼굴 사진", "몸 사진",
        "전신 사진", "거울 셀카", "네 얼굴", "네 몸", "누드", "나체",
    ),
    "fr": (
        "photo", "photos", "image", "images", "selfie", "selfies", "capture",
        "snap", "photo du visage", "photo du corps", "corps entier", "selfie miroir",
        "ton visage", "ton corps", "nu", "nue", "nus",
    ),
    "de": (
        "foto", "fotos", "bild", "bilder", "selfie", "selfies", "schnappschuss",
        "snapshot", "gesichtsfoto", "körperfoto", "ganzkörper", "spiegelselfie",
        "dein gesicht", "dein körper", "nackt", "nacktfoto",
    ),
    "it": (
        "foto", "fotografie", "immagine", "immagini", "selfie", "selfies", "scatto",
        "screenshot", "foto del viso", "foto del corpo", "corpo intero",
        "selfie allo specchio", "il tuo viso", "il tuo corpo", "nudo", "nuda",
    ),
    "nl": (
        "foto", "fotos", "afbeelding", "afbeeldingen", "selfie", "selfies", "snapshot",
        "screenshot", "gezichtsfoto", "lichaamsfoto", "hele lichaam", "spiegelselfie",
        "je gezicht", "je lichaam", "naakt",
    ),
    "sv": (
        "foto", "foton", "bild", "bilder", "selfie", "selfies", "ögonblicksbild",
        "skärmdump", "ansiktsbild", "kroppsbild", "helkropp", "spegelselfie",
        "ditt ansikte", "din kropp", "naken",
    ),
    "da": (
        "foto", "fotos", "billede", "billeder", "selfie", "selfies", "snapshot",
        "skærmbillede", "ansigtsbillede", "kropsbillede", "hele kroppen",
        "spejlselfie", "dit ansigt", "din krop", "nøgen",
    ),
    "no": (
        "foto", "bilder", "bilde", "selfie", "selfier", "snapshot", "skjermbilde",
        "ansiktsbilde", "kroppsbilde", "helkropp", "speilselfie", "ansiktet ditt",
        "kroppen din", "naken",
    ),
    "fi": (
        "kuva", "kuvat", "valokuva", "valokuvat", "selfie", "selfiet", "tilannekuva",
        "kuvakaappaus", "kasvokuva", "vartalokuva", "kokovartalo", "peiliselfie",
        "kasvosi", "vartalosi", "alaston", "alastonkuva",
    ),
    "is": (
        "mynd", "myndir", "ljósmynd", "ljósmyndir", "selfie", "sjálfsmynd",
        "skjáskot", "andlitsmynd", "líkamsmynd", "heil líkamsmynd", "spegilsjálfsmynd",
        "andlit þitt", "líkami þinn", "nakinn", "nakin",
    ),
    "el": (
        "φωτογραφία", "φωτογραφίες", "φωτο", "εικόνα", "εικόνες", "selfie",
        "στιγμιότυπο", "screenshot", "φωτογραφία προσώπου", "φωτογραφία σώματος",
        "ολόσωμη", "selfie στον καθρέφτη", "το πρόσωπό σου", "το σώμα σου",
        "γυμνό", "γυμνή",
    ),
    "cs": (
        "foto", "fotka", "fotku", "fotky", "fotografie", "obrázek", "obrázky",
        "selfie", "snímek", "screenshot", "fotka obličeje", "fotka těla",
        "celé tělo", "selfie v zrcadle", "tvůj obličej", "tvoje tělo", "nahý", "nahá",
    ),
}

_ASSET_VIDEO_BY_LANG: dict[str, tuple[str, ...]] = {
    "en": (
        "video", "videos", "vid", "vids", "clip", "clips", "movie", "gif", "tape",
        "recording", "custom video", "dirty video", "short clip", "private video", "bedroom video",
    ),
    "zh": ("视频", "视频文件", "小视频", "录像", "录制", "短片", "影片", "动图", "私密视频", "卧室视频"),
    "es": (
        "video", "videos", "vid", "vids", "videito", "clip", "clips", "película",
        "gif", "cinta", "grabación", "video personalizado", "video privado",
        "clip corto", "video íntimo",
    ),
    "pt": (
        "vídeo", "video", "videos", "vid", "clipe", "clip", "clips", "filme",
        "gif", "gravação", "video personalizado", "video privado", "clipe curto",
        "video íntimo",
    ),
    "ja": ("動画", "ビデオ", "クリップ", "短い動画", "映画", "gif", "録画", "録音", "カスタム動画", "プライベート動画"),
    "ko": ("영상", "비디오", "동영상", "클립", "짧은 영상", "영화", "gif", "녹화", "맞춤 영상", "개인 영상"),
    "fr": (
        "vidéo", "video", "vidéos", "videos", "clip", "clips", "film", "gif",
        "enregistrement", "vidéo personnalisée", "vidéo privée", "court clip",
    ),
    "de": (
        "video", "videos", "clip", "clips", "film", "gif", "aufnahme",
        "kundenvideo", "personalisiertes video", "privates video", "kurzer clip", "filmchen",
    ),
    "it": (
        "video", "videos", "clip", "clips", "film", "gif", "registrazione",
        "video personalizzato", "video privato", "breve clip",
    ),
    "nl": (
        "video", "videos", "clip", "clips", "film", "gif", "opname",
        "aangepaste video", "privévideo", "korte clip",
    ),
    "sv": (
        "video", "videor", "videos", "klipp", "film", "gif", "inspelning",
        "anpassad video", "privat video", "kort klipp",
    ),
    "da": (
        "video", "videoer", "videos", "klip", "film", "gif", "optagelse",
        "tilpasset video", "privat video", "kort klip",
    ),
    "no": (
        "video", "videoer", "videos", "klipp", "film", "gif", "opptak",
        "tilpasset video", "privat video", "kort klipp",
    ),
    "fi": (
        "video", "videot", "klippi", "klipit", "elokuva", "gif", "tallenne",
        "oma video", "yksityinen video", "lyhyt klippi",
    ),
    "is": (
        "myndband", "myndbönd", "klipp", "kvikmynd", "gif", "upptaka",
        "sérsniðið myndband", "einkamyndband", "stutt klipp",
    ),
    "el": (
        "βίντεο", "βιντεο", "κλιπ", "ταινία", "gif", "εγγραφή",
        "προσωπικό βίντεο", "ιδιωτικό βίντεο", "σύντομο κλιπ",
    ),
    "cs": (
        "video", "videa", "klip", "klipy", "film", "gif", "nahrávka",
        "vlastní video", "soukromé video", "krátký klip",
    ),
}

_ASSET_REQUEST_BY_LANG: dict[str, tuple[str, ...]] = {
    "en": (
        "send", "show", "see", "watch", "look", "view", "share", "drop", "give", "upload",
        "want", "wanna", "need", "can i", "could i", "may i", "let me", "lemme", "please",
        "pls", "have", "got", "any", "do you have", "you have",
    ),
    "zh": ("想", "想看", "想要", "要", "看", "发", "发送", "展示", "分享", "有", "有没有", "给我", "发来", "可以看", "请"),
    "es": (
        "mándame", "mandame", "mándamelo", "mandamelo", "envíame", "enviame",
        "envíamelo", "enviamelo", "muéstrame", "muestrame", "muestra",
        "pasame", "pásame", "pásamela", "pasamela", "dame", "dale", "crea", "crear",
        "manda", "envia", "envía", "quiero ver", "puedo ver", "ver de cerca",
        "ver de más", "más de cerca",
    ),
    "pt": (
        "me manda", "me mande", "me envia", "me envie", "mostra", "mostre", "quero ver",
        "pode mandar", "manda", "envia", "compartilha", "me dá", "tem", "você tem",
    ),
    "ja": ("送って", "見せて", "見たい", "欲しい", "ちょうだい", "くれ", "共有して", "アップして", "ある", "持ってる"),
    "ko": ("보내", "보여", "보고 싶", "줘", "원해", "보내줘", "공유해", "올려줘", "있어", "가지고 있어"),
    "fr": ("envoie", "envoyez", "montre", "montrez", "je veux voir", "donne", "donnez", "partage", "tu as", "as-tu"),
    "de": ("schick", "schick mir", "zeig", "zeige", "ich will sehen", "gib mir", "sende", "teile", "hast du"),
    "it": ("mandami", "invia", "mostrami", "voglio vedere", "dammi", "manda", "condividi", "hai"),
    "nl": ("stuur", "stuur me", "laat zien", "ik wil zien", "geef me", "deel", "heb je"),
    "sv": ("skicka", "visa", "jag vill se", "ge mig", "skicka mig", "dela", "har du"),
    "da": ("send", "vis", "jeg vil se", "giv mig", "send mig", "del", "har du"),
    "no": ("send", "vis", "jeg vil se", "gi meg", "send meg", "del", "har du"),
    "fi": ("lähetä", "näytä", "haluan nähdä", "anna minulle", "jaa", "onko sinulla"),
    "is": ("sendu", "sýndu", "ég vil sjá", "gefðu mér", "deildu", "ertu með"),
    "el": ("στείλε", "δείξε", "θέλω να δω", "δώσε μου", "μοιράσου", "έχεις"),
    "cs": ("pošli", "ukaž", "chci vidět", "dej mi", "pošli mi", "sdílej", "máš"),
}

_VIDEO_CALL_BY_LANG: dict[str, tuple[str, ...]] = {
    "en": (
        "video call", "videocall", "facetime", "face time", "cam2cam", "c2c",
        "live show", "private call", "video chat",
    ),
    "zh": ("视频通话", "视频电话", "打视频", "开视频", "视讯", "视频聊天", "私密通话", "直播", "裸聊"),
    "es": (
        "videollamada", "videollamadas", "llamada de video", "llamada por video",
        "videollamada conmigo", "video chat", "chat de video", "llamada privada",
        "show en vivo", "camara a camara", "cámara a cámara",
    ),
    "pt": (
        "chamada de video", "chamada de vídeo", "videochamada", "ligação de vídeo",
        "chat de video", "chat de vídeo", "chamada privada", "show ao vivo",
        "camera com camera", "câmera com câmera",
    ),
    "ja": ("ビデオ通話", "ビデオチャット", "ビデオ電話", "通話して", "フェイスタイム", "カメラ通話", "ライブ通話", "プライベート通話"),
    "ko": ("영상통화", "화상통화", "영상 채팅", "영상전화", "페이스타임", "캠투캠", "라이브 쇼", "개인 통화"),
    "fr": ("appel vidéo", "appel video", "facetime", "face time", "visio", "visiochat", "chat vidéo", "appel privé", "show en direct"),
    "de": ("videoanruf", "video anruf", "facetime", "face time", "video chat", "videochat", "privater anruf", "live show", "cam zu cam"),
    "it": ("videochiamata", "chiamata video", "facetime", "face time", "video chat", "chat video", "chiamata privata", "spettacolo live"),
    "nl": ("videogesprek", "video bellen", "facetime", "face time", "videochat", "videocall", "privégesprek", "live show"),
    "sv": ("videosamtal", "video samtal", "facetime", "face time", "videochatt", "privat samtal", "liveshow", "cam till cam"),
    "da": ("videoopkald", "video opkald", "facetime", "face time", "videochat", "privat opkald", "liveshow", "cam til cam"),
    "no": ("videosamtale", "video samtale", "facetime", "face time", "videochat", "privat samtale", "liveshow", "cam til cam"),
    "fi": ("videopuhelu", "video puhelu", "facetime", "face time", "videochat", "yksityinen puhelu", "live show", "kamerasta kameraan"),
    "is": ("myndsímtal", "myndsamtal", "facetime", "face time", "myndspjall", "einkasímtal", "bein sýning", "myndavél við myndavél"),
    "el": ("βιντεοκλήση", "βιντεο κλήση", "facetime", "face time", "video chat", "βιντεοσυνομιλία", "ιδιωτική κλήση", "ζωντανό show"),
    "cs": ("videohovor", "video hovor", "facetime", "face time", "video chat", "videochat", "soukromý hovor", "živá show", "kamera na kameru"),
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

INBOUND_CALL_REDIRECT_COPY: dict[str, str] = _require_language_table(
    {
        "en": "I can't call you from my side. Tap the video call button on my profile and I'll answer there.",
        "zh": "我这边不能主动打给你。你点我资料页上的视频通话按钮打过来，我会接。",
        "es": "No puedo llamarte desde mi lado. Toca el botón de videollamada en mi perfil y te contesto ahí.",
        "pt": "Eu não consigo ligar para você por aqui. Toque no botão de videochamada no meu perfil e eu atendo por lá.",
        "ja": "こちらからは発信できないよ。プロフィールのビデオ通話ボタンを押してくれたら、そこで出るね。",
        "ko": "내 쪽에서는 먼저 걸 수 없어. 내 프로필의 영상통화 버튼을 눌러주면 거기서 받을게.",
        "fr": "Je ne peux pas t'appeler de mon côté. Appuie sur le bouton d'appel vidéo de mon profil et je répondrai là-bas.",
        "de": "Ich kann dich von meiner Seite nicht anrufen. Tippe auf die Videoanruf-Schaltfläche in meinem Profil, dann gehe ich dort ran.",
        "it": "Non posso chiamarti io da qui. Tocca il pulsante di videochiamata sul mio profilo e ti rispondo lì.",
        "nl": "Ik kan jou niet vanaf mijn kant bellen. Tik op de videogesprekknop op mijn profiel, dan neem ik daar op.",
        "sv": "Jag kan inte ringa dig från min sida. Tryck på videosamtalsknappen på min profil så svarar jag där.",
        "da": "Jeg kan ikke ringe dig herfra. Tryk på videoopkaldsknappen på min profil, så svarer jeg der.",
        "no": "Jeg kan ikke ringe deg herfra. Trykk på videosamtale-knappen på profilen min, så svarer jeg der.",
        "fi": "En voi soittaa sinulle tältä puolelta. Napauta profiilini videopuhelupainiketta, niin vastaan siellä.",
        "is": "Ég get ekki hringt í þig héðan. Ýttu á myndsímtalshnappinn á prófílnum mínum og ég svara þar.",
        "el": "Δεν μπορώ να σε καλέσω από τη δική μου πλευρά. Πάτα το κουμπί βιντεοκλήσης στο προφίλ μου και θα απαντήσω εκεί.",
        "cs": "Nemůžu ti volat z mé strany. Klepni na tlačítko videohovoru v mém profilu a tam to zvednu.",
    },
    name="INBOUND_CALL_REDIRECT_COPY",
)

_OUTBOUND_STANDALONE_CALL_TOKENS = frozenset(
    {"call", "ring", "phone", "videocall", "video call", "videochat", "facetime"}
)

_INBOUND_CALL_HELP_RE = re.compile(
    r"(?:"
    r"\bd[oó]nde te llamo\b|"
    r"\bd[oó]nde te marco\b|"
    r"\bc[oó]mo te llamo\b|"
    r"\bhow (?:do|can) i call\b|"
    r"\bwhere (?:do|can) i call\b|"
    r"\bcomo te llamo\b|"
    r"\bonde te ligo\b|"
    r"\b(?:how do i call|how can i call|where do i call|how to call|which button)\b|"
    r"\b(?:how do i video call|how can i video call|where is the video call)\b|"
    r"\b(?:como llamo|cómo llamo|como hago videollamada|cómo hago videollamada)\b|"
    r"\b(?:como ligo|como faço chamada de vídeo|como faco chamada de video)\b|"
    r"(?:怎么打视频|怎么视频|怎么打给你|哪里打视频|哪个按钮|怎么打(?:给你|过来))|"
    r"(?:どうやって通話|どこで通話|どのボタン)|"
    r"(?:어떻게 통화|어느 버튼)"
    r")",
    re.IGNORECASE | re.UNICODE,
)

_OUTBOUND_CALL_REQUEST_RE = re.compile(
    r"(?:"
    r"\b(?:ll[aá]mame|llamame|ll[aá]mame bb|llama(?:me)? ac[aá]|llama aqu[ií]|"
    r"llama en telegram|ll[aá]mame en telegram)\b|"
    r"\b(?:call me|ring me|phone me|you call me|video call me|facetime me)\b|"
    r"\b(?:can|could|will) you call\b|"
    r"\b(?:can you video call|can u video call|could you video call)\b|"
    r"\b(?:me puedes|puedes) (?:llamar|hacer|iniciar)\b|"
    r"\b(?:me puedes hacer|hazme) (?:una )?(?:llamada|videollamada)\b|"
    r"\b(?:iniciar|hacer) (?:una )?videollamada\b|"
    r"\b(?:me llamas|ll[aá]mame ahora)\b|"
    r"\b(?:voc[eê] pode|voce pode|pode me) (?:ligar|chamar|fazer)\b|"
    r"\b(?:pode me ligar|me liga)\b|"
    r"\?[^.!?]{0,40}\b(?:videollamada|video call)\b|"
    r"\b(?:videollamada|llamada de video|videochamada|chamada de vídeo)\b|"
    r"\b(?:打给我|你打过来|给我打)\b|"
    r"(?:视频通话|视频电话|打视频|开视频|裸聊|ビデオ通話|영상통화|화상通话|화상통화)"
    r")",
    re.IGNORECASE | re.UNICODE,
)

_OUTBOUND_CALL_PROMISE_RE = re.compile(
    r"(?:"
    r"\b(?:te llamar[eé]|te llamo ahora|te marco ahora|llamar[eé] ahora)\b|"
    r"\b(?:i(?:'ll| will) call you|calling you now|i(?:'m| am) calling you|i'm dialing you)\b|"
    r"\b(?:vou te ligar|ligo (?:pra|para) voc[eê] agora)\b|"
    r"\b(?:我现在打给你|这就给你打)\b"
    r")",
    re.IGNORECASE | re.UNICODE,
)

_EN_VIDEO_CALL_HINT_RE = re.compile(
    r"\b(?:video call|videocall|facetime|face time|cam2cam|c2c|"
    r"video chat|private call|live show|call me|ring me|phone me)\b",
    re.IGNORECASE,
)

OUTBOUND_VIDEO_CALL_ACK_COPY: dict[str, str] = _require_language_table(
    {
        "en": "Got it — give me a sec, I'm lining up your video call now.",
        "zh": "收到，稍等一下，我这边给你安排视频通话。",
        "es": "Entendido — dame un segundo, estoy preparando tu videollamada.",
        "pt": "Entendi — me dá um segundo, estou organizando sua videochamada.",
        "ja": "了解 — ちょっと待ってね、今ビデオ通話を手配してるよ。",
        "ko": "알겠어 — 잠깐만, 지금 영상통화 준비 중이야.",
        "fr": "Compris — une seconde, je prépare ton appel vidéo.",
        "de": "Alles klar — gib mir eine Sekunde, ich richte deinen Videoanruf ein.",
        "it": "Capito — dammi un secondo, sto organizzando la tua videochiamata.",
        "nl": "Begrepen — geef me een seconde, ik regel je videogesprek.",
        "sv": "Okej — ge mig en sekund, jag ordnar ditt videosamtal.",
        "da": "Forstået — giv mig et øjeblik, jeg sætter dit videoopkald op.",
        "no": "Skjønner — gi meg et sekund, jeg ordner videosamtalen din.",
        "fi": "Selvä — anna hetki, järjestän videopuhelusi.",
        "is": "Allt í lagi — gefðu mér sekúndu, ég er að útbúa myndsímtalið þitt.",
        "el": "Το κατάλαβα — δώσε μου ένα δευτερόλεπτο, ετοιμάζω την βιντεοκλήση σου.",
        "cs": "Jasně — dej mi chvilku, připravuji tvůj videohovor.",
    },
    name="OUTBOUND_VIDEO_CALL_ACK_COPY",
)


def is_inbound_call_help_request(user_text: str | None) -> bool:
    """User asks how/where to call the bot — guide inbound, not outbound handoff."""
    text = " ".join(str(user_text or "").casefold().split())
    return bool(text and _INBOUND_CALL_HELP_RE.search(text))


def is_outbound_call_request(user_text: str | None) -> bool:
    """True when the user wants the bot to initiate the call."""
    text = " ".join(str(user_text or "").casefold().replace("'", "'").split())
    if not text or is_inbound_call_help_request(text):
        return False
    if text in _OUTBOUND_STANDALONE_CALL_TOKENS:
        return True
    return bool(_OUTBOUND_CALL_REQUEST_RE.search(text))


def inbound_call_redirect_reply(
    user_text: str | None = None,
    *,
    language: str | None = None,
) -> str:
    """Ask the user to tap inbound video call on profile (cannot dial outbound)."""
    if language:
        lang = normalize_product_language(language, default="en")
    elif _EN_VIDEO_CALL_HINT_RE.search(str(user_text or "")):
        lang = "en"
    else:
        lang = normalize_product_language(
            detect_language_from_text(user_text or "", default="en"),
            default="en",
        )
    return pick_localized(INBOUND_CALL_REDIRECT_COPY, lang)


def outbound_video_call_ack_reply(
    user_text: str | None = None,
    *,
    language: str | None = None,
) -> str:
    """User asked for a live/outbound video call — acknowledge and queue operator."""
    lang = normalize_product_language(
        language or detect_language_from_text(user_text or "", default="en"),
        default="en",
    )
    return pick_localized(OUTBOUND_VIDEO_CALL_ACK_COPY, lang)


def strip_outbound_call_promises(text_value: str | None, *, user_text: str | None = None) -> str:
    """Remove LLM lines promising to call the user when they asked for outbound."""
    if not is_outbound_call_request(user_text):
        return str(text_value or "").strip()
    parts = re.split(r"(?<=[.!?。！？])\s+", str(text_value or "").strip())
    kept = [part.strip() for part in parts if part.strip() and not _OUTBOUND_CALL_PROMISE_RE.search(part)]
    return " ".join(kept).strip()
