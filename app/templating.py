"""Request-local gettext context; never mutate shared Jinja globals."""
from app.localization import supported_language, translations_for, SUPPORTED_LANGUAGES


def localization_context(request):
    language = supported_language(getattr(request.state, 'language', 'en'))
    translations = translations_for(language)
    _ = translations.gettext
    action_labels = {'edit': _('Edit'), 'present': _('Present'), 'share': _('Share'), 'check': _('Check')}
    return {'action_labels': action_labels, 'language': language, '_': translations.gettext, 'ngettext': translations.ngettext,
            'language_options': SUPPORTED_LANGUAGES}
