def parse_tg_proxy(url: str):
    if not url or not url.startswith("tg://proxy?"):
        return None, None, None
    query = url[len("tg://proxy?"):]
    params = {}
    for part in query.split("&"):
        if "=" in part:
            k, v = part.split("=", 1)
            params[k] = v
    server = params.get("server")
    port = int(params.get("port", 0)) if params.get("port") else None
    secret = params.get("secret")
    return server, port, secret
