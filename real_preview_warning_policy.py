"""Account-bound explicit consent; absence/revocation keeps warnings blocked."""
from datetime import datetime,timezone


def accepted_warning_codes(config,binding,*,now=None):
    consent=config.get('preview_warning_consent') or {}
    try:
        accepted=datetime.fromisoformat(consent['accepted_at'])
        if accepted.tzinfo is None or accepted>(now or datetime.now(timezone.utc)):return ()
        if (consent.get('binding')==binding and consent.get('accepted') is True
            and consent.get('codes')==['SEV25']):return ('SEV25',)
    except (KeyError,TypeError,ValueError):pass
    return ()
