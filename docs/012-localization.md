# Account language preferences

OakGate reuses Safebox Web's gettext approach and language catalogs. English is
the default. Preferences offers French, Spanish, Portuguese, German, Italian,
Inuktitut and Simplified Chinese as well. Inuktitut retains Safebox Web's limited,
provisional translations and requires fluent-speaker review.

Choose **Preferences → Preferred language**, then **Save preferences**. OakGate
stores the choice in `user_display_preferences` in its existing `custody.sqlite3`,
keyed by the user's issuer/subject identity. It works before an Acorn is connected,
with an empty handle, after signing in again, and across devices. Clearing a handle
does not clear the language. Handle and language updates share one transaction;
a conflicting handle does not partially change preferences.

There is no language cookie. Redis sessions do not retain the language. Each
signed-in request reads the saved preference, and Jinja receives a request-local
translator. The shared template environment is never switched between languages.
The HTML language and Content-Language header reflect the selection. Anonymous
pages default to English; Google and Keycloak keep their own language settings.

The existing SQLite backup includes language preferences automatically. Startup
adds the new table without changing existing handles, wallet mappings or records.
Existing users default to English until they choose a language.

## Translation scope

Account templates mark application UI text for translation. Navigation, preference
controls and common record/transaction controls have OakGate-specific vocabulary
in the six broadly translated catalogs. Existing Safebox Web translations are
retained. Untranslated OakGate explanations and errors deliberately fall back to
English; this is not a claim of complete or professionally reviewed translation.
User names, handles, record labels and contents, transaction comments, identifiers,
addresses and friendly asset units are never passed through gettext. Numeric/date
formatting and the public landing page are unchanged in this iteration.

## Updating catalogs

Runtime uses Python's standard gettext library and the committed `.mo` files;
containers copy the catalogs with `app/` and need no translation compiler.
Translation maintenance uses Babel from the docs dependency group:

```sh
poetry install --with docs
poetry run pybabel extract -k N_ -k error_page:2 -F babel.cfg -o /tmp/oakgate-messages.pot .
poetry run pybabel update -i /tmp/oakgate-messages.pot -d app/locales
poetry run pybabel compile -d app/locales
poetry run pytest tests/test_localization.py
```

Review `.po` changes before compiling and commit both `.po` and `.mo`. Restart the
app after changing catalogs because gettext objects are cached. Keep interpolation
placeholders intact and use English fallback for unreviewed translations rather
than inventing terminology. Reuse this approach for future account controls.


## Expanded screens and Inuktitut demonstration

The account screens now extract labels in the scanner, product and OpenETR
views as well as Funds, Records, Receipts, Preferences, Send and Receive.
Scanner status, PDF paging and copy feedback receive a request-local JSON
translation dictionary. `tojson` escapes that dictionary; browser code displays
translations as text, never HTML. User records, handles, balances, asset units
and signed publisher statements remain untouched. English remains the fallback
for untranslated technical explanations and errors; this is not full coverage.

Each of French, Spanish, Portuguese, German, Italian and Simplified Chinese gained
120 common-screen translations in this pass. Inuktitut has 26 additional or
refined demonstration labels. Per the product decision, those labels display
syllabics alone, without appended English. Preferences identifies the demonstration
and the need for fluent-speaker review. Financial warnings and specialized terms
without a reviewed translation remain English. These are draft UI adaptations,
not certified translations; do not mark them reviewed without a fluent reviewer.

The existing provisional catalog and these references informed the demonstration:
- [Pirurvik Tusaalanga: work and money vocabulary](https://www.tusaalanga.ca/node/1096)
- [Qikiqtani Inuit Association: language vocabulary](https://www.qia.ca/word-of-the-day/)

These references support vocabulary, not certification of the UI sentences.
A reviewer should confirm dialect, terminology, possessive forms, button verbs and
payment language before a broader Inuktitut release.

Syllabics use the bundled Noto Sans Canadian Aboriginal variable font, distributed
under the SIL Open Font License (license stored beside the font). It is loaded
from OakGate itself, never a font CDN. Navigation wraps on smaller screens and
syllabic headings avoid condensed letter spacing. Font source:
https://github.com/google/fonts/tree/main/ofl/notosanscanadianaboriginal

For a demo, save Inuktitut in Preferences, then visit Funds, Records, Receipts,
Receive and Preferences on mobile and desktop. Confirm syllabics render and
record labels stay exactly as supplied. Sign into another account to confirm
preferences remain account-specific. Restart the app after catalog changes.

## French coverage review

The French catalog now covers all currently extracted account-screen messages,
including setup, payment review, recovery warnings, records, sharing, scanner,
PDF previews and OpenETR explanations. Static messages passed to `error_page`
are also translated; include `-k error_page:2` during extraction to retain them.
Recovery placeholders and record-preview accessibility labels now use gettext.
The current balance headings are **Everyday Funds** (“Fonds du quotidien”) and
**Community Credits** (“Crédits communautaires”). Older Cash balance entries remain
in the catalogs for controls that still use them; Clear remains a technical product
name. User content and public identifiers are unchanged.

A regression test checks that every marked template message, marked Python
message and static error-page message has an entry in the compiled French
catalog, including plural forms. This is source-message coverage, not a claim
that arbitrary backend exceptions, third-party protocol findings, user content,
the anonymous landing page or Keycloak are translated. New dynamic display
messages must be marked for extraction and translated separately.

## Prominent action-label demonstration

The demonstration now translates prominent payment, setup, recovery, scanner and
record buttons across Spanish, Portuguese, German, Italian and Simplified Chinese.
Inuktitut additionally covers Scan, sign-out, record editing/presentation/sharing,
request creation, message sending, list/folder navigation and common form labels.
Translated Inuktitut actions use syllabics without English appended. User-supplied
units in “Send %(unit)s” remain unchanged, as do product names and identifiers.

These Inuktitut labels are provisional UI adaptations, not certified translations.
The existing Preferences notice remains. Longer instructions and safety warnings
still fall back to English; label coverage is not full language coverage. Fluent
review of dialect, imperatives and financial terminology is required before
presenting the demonstration as a fully localized service. Microsoft's
[Inuktitut localization style guide](https://download.microsoft.com/download/0/b/6/0b65bcfe-5fac-4b20-86fe-f613200667c1/iku-can-styleguide.pdf)
was consulted for language conventions, not as certification of these labels.
