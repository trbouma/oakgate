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
poetry run pybabel extract -k N_ -F babel.cfg -o /tmp/oakgate-messages.pot .
poetry run pybabel update -i /tmp/oakgate-messages.pot -d app/locales
poetry run pybabel compile -d app/locales
poetry run pytest tests/test_localization.py
```

Review `.po` changes before compiling and commit both `.po` and `.mo`. Restart the
app after changing catalogs because gettext objects are cached. Keep interpolation
placeholders intact and use English fallback for unreviewed translations rather
than inventing terminology. Reuse this approach for future account controls.
