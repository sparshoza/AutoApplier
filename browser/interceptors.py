import logging

logger = logging.getLogger("job_pilot.interceptors")


def register_interceptors(page, on_popup_during_apply=None):
    """Register all interceptors on a page BEFORE any navigation occurs."""

    page.on("dialog", _handle_dialog)
    page.on("popup", lambda popup: _handle_popup(popup, on_popup_during_apply))
    page.on("filechooser", _handle_filechooser)


async def _handle_dialog(dialog):
    logger.warning("Dismissed %s dialog: %s", dialog.type, dialog.message[:120])
    try:
        await dialog.dismiss()
    except Exception:
        pass


def _handle_popup(popup, on_popup_callback):
    logger.warning("Blocked popup: %s", popup.url[:200])
    try:
        popup.close()
    except Exception:
        pass
    if on_popup_callback:
        on_popup_callback("Unexpected popup blocked")


def _handle_filechooser(file_chooser):
    logger.warning(
        "OS file chooser triggered unexpectedly — this should not happen. "
        "Resume uploads must use Playwright file injection."
    )
