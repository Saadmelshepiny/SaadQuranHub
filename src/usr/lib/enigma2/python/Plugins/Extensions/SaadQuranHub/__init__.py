# -*- coding: utf-8 -*-
# 2.0: if a fresh update cannot even be imported, the previous version (kept on the HDD) is put back.
try:
    from . import plugin  # noqa: F401
except Exception:
    try:
        from . import safeupdate
        if safeupdate.auto_rollback():
            from . import plugin  # noqa: F401,F811
    except Exception:
        pass
