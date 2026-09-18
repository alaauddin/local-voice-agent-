import logging

import httpx
from django.conf import settings

from kiosk_agent.models import ChaletConfig

logger = logging.getLogger(__name__)


def _resolve_config(config: ChaletConfig | None) -> tuple[str, str, str, float, bool]:
    try:
        cfg = config or ChaletConfig.load()
    except Exception:
        cfg = None
        return settings.SAAS_INTEGRATION_URL.strip(), settings.SAAS_INTEGRATION_TOKEN.strip(), settings.SAAS_TENANT_SUBDOMAIN.strip(), float(getattr(settings, "SAAS_TIMEOUT_SECONDS", 5) or 5), bool(getattr(settings, "SAAS_INTEGRATION_ENABLED", False))
    url = (cfg.saas_integration_url or "").strip()
    token = (cfg.saas_integration_token or "").strip()
    tenant = (cfg.saas_tenant_subdomain or "").strip()
    timeout = float(cfg.saas_timeout_seconds or getattr(settings, "SAAS_TIMEOUT_SECONDS", 5) or 5)
    enabled = bool(cfg.saas_enabled)
    if not url:
        url = settings.SAAS_INTEGRATION_URL.strip()
        token = token or settings.SAAS_INTEGRATION_TOKEN.strip()
        tenant = tenant or settings.SAAS_TENANT_SUBDOMAIN.strip()
        enabled = enabled or bool(getattr(settings, "SAAS_INTEGRATION_ENABLED", False))
        if not cfg.saas_integration_url and not cfg.saas_integration_token and not cfg.saas_tenant_subdomain:
            timeout = float(getattr(settings, "SAAS_TIMEOUT_SECONDS", 5) or 5)
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
    headers = {"Content-Type": "application/json"}
    if token:
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
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(url, json=payload, headers=headers)
            try:
                data = resp.json()
            except Exception:
                data = {"raw": resp.text[:2000]}
            if 200 <= resp.status_code < 300:
                logger.info("SaaS forwarded %s -> %s", local_reference, url)
                return {"forwarded": True, "status_code": resp.status_code, "response": data}
            logger.warning("SaaS forward failed %s %s: %s", resp.status_code, url, resp.text[:500])
            return {"forwarded": False, "status_code": resp.status_code, "response": data, "reason": "http_error"}
    except Exception as exc:
        logger.warning("SaaS forward exception %s: %s", url, exc)
        return {"forwarded": False, "reason": "exception", "error": str(exc)[:500]}
