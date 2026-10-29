"""Request-local gettext context; never mutate shared Jinja globals."""
from app.record_labels import display_record_label
from app.localization import supported_language, translations_for, SUPPORTED_LANGUAGES


def localization_context(request):
    language = supported_language(getattr(request.state, 'language', 'en'))
    translations = translations_for(language)
    _ = translations.gettext
    action_labels = {'edit': _('Edit'), 'present': _('Present'), 'share': _('Share'), 'check': _('Check'), 'delete': _('Delete')}
    return {'record_display_label': display_record_label, 'action_labels': action_labels, 'language': language, '_': translations.gettext, 'ngettext': translations.ngettext,
            'language_options': SUPPORTED_LANGUAGES}
