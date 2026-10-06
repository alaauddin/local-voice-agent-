import logging

import httpx
from django.conf import settings

from kiosk_agent.models import ChaletConfig

logger = logging.getLogger(__name__)


def _is_placeholder_url(url: str) -> bool:
    lowered = (url or "").strip().lower()
    return (
        not lowered
        or "localhost" in lowered
        or "127.0.0.1" in lowered
        or "example.com" in lowered
    )


def _resolve_config(config: ChaletConfig | None) -> tuple[str, str, str, float, bool]:
    env_url = (settings.SAAS_INTEGRATION_URL or "").strip()
    env_token = (settings.SAAS_INTEGRATION_TOKEN or "").strip()
    env_tenant = (settings.SAAS_TENANT_SUBDOMAIN or "").strip()
    try:
        env_timeout = float(getattr(settings, "SAAS_TIMEOUT_SECONDS", 5) or 5)
    except (TypeError, ValueError):
        env_timeout = 5.0
    env_enabled = bool(getattr(settings, "SAAS_INTEGRATION_ENABLED", False))

    try:
        cfg = config or ChaletConfig.load()
    except Exception:
        return env_url, env_token, env_tenant, env_timeout, env_enabled

    db_url = ((cfg.saas_integration_url or "").strip())
    db_token = ((cfg.saas_integration_token or "").strip())
    db_tenant = ((cfg.saas_tenant_subdomain or "").strip())
    try:
        db_timeout = float(cfg.saas_timeout_seconds or env_timeout or 5)
    except (TypeError, ValueError):
        db_timeout = env_timeout
    db_enabled = bool(cfg.saas_enabled)

    # DB wins when it holds a real (non-placeholder) URL, otherwise fall back
    # to the environment so a stale localhost row can never shadow .env.
    if _is_placeholder_url(db_url):
        url, token, tenant = env_url, env_token or db_token, env_tenant or db_tenant
        timeout = env_timeout if _is_placeholder_url(db_url) and not db_url else db_timeout
        # If the DB row was never configured, the env timeout is authoritative.
        if not db_url and not db_token and not db_tenant:
            timeout = env_timeout
    else:
        url = db_url or env_url
        token = db_token or env_token
        tenant = db_tenant or env_tenant
        timeout = db_timeout
    enabled = db_enabled or env_enabled
    return url, token, tenant, timeout, enabled


async def forward_request_to_saas(
    *,
    config: ChaletConfig,
    service: str,
    details: str,
    urgency: str,
    stay_id: str,
    request_id: str,
    local_reference: str,
) -> dict:
    url, token, tenant, timeout, enabled = _resolve_config(config)
    if not enabled or not url:
        return {"forwarded": False, "reason": "disabled_or_no_url"}
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    if token:
        # SaaS (DRF) accepts the kiosk token via these headers; send all
        # variants so TokenAuthentication and custom middleware both match.
        headers["Authorization"] = f"Token {token}"
        headers["X-Kiosk-Token"] = token
        headers["X-API-Key"] = token
    if tenant:
        headers["X-Tenant"] = tenant
        headers["X-Subdomain"] = tenant
    payload = {
        "chalet_number": config.chalet_number,
        "chalet_name": config.chalet_name,
        "service": service,
        "details": details,
        "urgency": urgency,
        "stay_id": stay_id,
        "request_id": request_id,
        "local_reference": local_reference,
        "source": "wazen-local",
        "tenant_subdomain": tenant,
        "payload": {
            "chalet_number": config.chalet_number,
            "chalet_name": config.chalet_name,
            "persona_name": config.persona_name,
            "service": service,
            "details": details,
            "urgency": urgency,
            "stay_id": stay_id,
            "request_id": request_id,
            "local_reference": local_reference,
            "property_facts": config.property_facts,
            "enabled_services": config.enabled_services,
        },
    }
    try:
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            resp = await client.post(url, json=payload, headers=headers)
            try:
                data = resp.json()
            except Exception:
                data = {"raw": resp.text[:2000]}
            if 200 <= resp.status_code < 300:
                logger.info("SaaS forwarded %s -> %s", local_reference, url)
                return {"forwarded": True, "status_code": resp.status_code, "response": data}
            body = resp.text[:500] if isinstance(resp.text, str) else ""
            logger.warning("SaaS forward failed %s %s: %s", resp.status_code, url, body)
            return {
                "forwarded": False,
                "status_code": resp.status_code,
                "response": data,
                "reason": "http_error",
                "error": f"http_{resp.status_code}: {body}".strip()[:500],
            }
    except Exception as exc:
        logger.warning("SaaS forward exception %s: %s", url, exc)
        return {"forwarded": False, "reason": "exception", "error": str(exc)[:500]}
