# Přehraj.to upload flow (reverse-engineered HTTP)

Ověřeno end-to-end 2026-04-18 na `olbrasoft.claudecode@gmail.com` Premium účtu.
Funguje **bez prohlížeče**, čistě přes HTTP.

## Endpointy

| # | URL | Metoda | Content-Type |
|---|-----|--------|---------------|
| 0 | `https://prehraj.to/` | GET | — (priming) |
| 1 | `https://prehraj.to/?frm=homepageLoginForm-loginForm` | POST | multipart/form-data |
| 2 | `https://prehraj.to/profil/nahrat-soubor?do=prepareVideo` | POST | application/x-www-form-urlencoded |
| 3 | `https://api.premiumcdn.net/upload/` | POST | multipart/form-data |

## Krok 0: Priming GET (POVINNÉ)

```http
GET https://prehraj.to/ HTTP/1.1
User-Agent: Mozilla/5.0 ...
```

Server odpoví 200 + Set-Cookie:
- `_nss=1`
- `u_uid=u_...` (per-browser ID, i pro nepřihlášeného)
- `flash-message-user-hash=...`

Bez tohoto kroku Krok 1 projde se statusem 200, ale session se nevytvoří
správně. `redirect` v odpovědi vrátí `https://prehraj.to/` (místo
`https://prehraj.to/?afterLogin=1`), další requesty 302 → login.

## Krok 1: Login

```http
POST https://prehraj.to/?frm=homepageLoginForm-loginForm HTTP/1.1
X-Requested-With: XMLHttpRequest
Accept: application/json
Referer: https://prehraj.to/
Content-Type: multipart/form-data; boundary=...

------boundary
Content-Disposition: form-data; name="email"

olbrasoft.claudecode@gmail.com
------boundary
Content-Disposition: form-data; name="password"

...
------boundary
Content-Disposition: form-data; name="_do"

homepageLoginForm-loginForm-submit
------boundary
Content-Disposition: form-data; name="login"

Přihlásit se
------boundary--
```

Odpověď (200, JSON):

```json
{"redirect":"https://prehraj.to/?afterLogin=1","state":[]}
```

Úspěch = `redirect` obsahuje `afterLogin=1`.

Set-Cookie (HttpOnly, Secure, Lax):
- `access_token` — JWT, ~10 min expirace
- `refresh_token` — 2 roky expirace
- `alreadyLoggedIn=true`

### Volitelné: `remember_login=on` pole

Uživatelské UI má checkbox „Přihlásit mě automaticky při další návštěvě".
Pokud ho zaškrtneš, přidej další form field `remember_login=on`. Na
JWT refresh tokenu to zřejmě nemá vliv (i bez toho je refresh_token
nastavený na 2 roky), ale pro jistotu to posíláme.

## Krok 2: `prepareVideo`

```http
POST https://prehraj.to/profil/nahrat-soubor?do=prepareVideo HTTP/1.1
X-Requested-With: XMLHttpRequest
Accept: */*
Content-Type: application/x-www-form-urlencoded; charset=UTF-8
Cookie: _nss=1; access_token=...; refresh_token=...

description=&name=film.mp4&size=6126070&type=video%2Fmp4&erotic=false&folder=&private=true
```

Pole:
- `description` — typically `""`
- `name` — filename s příponou (zobrazí se v UI)
- `size` — velikost v bytes (string)
- `type` — MIME type (`video/mp4`)
- `erotic` — `true`/`false`
- `folder` — empty nebo ID složky v účtu
- `private` — `true`/`false` (pozn.: velmi malé soubory < ~10 kB flag
  ignorují a jdou jako veřejné)

Odpověď (200, JSON):

```json
{
  "nonce": "5de0ed5601ac4b6f598c6d1148fc397d",
  "params": "{\"video_id\":23955372,\"videoId\":23955372}",
  "project": "1",
  "response": "JSON",
  "signature": "3b5cd71eb41bf30acf27e6fa9e24381af9d570ea"
}
```

- `video_id` v `params` = ID v DB Přehraj.to.
- `nonce` + `signature` = server-side HMAC pro Krok 3.
- Všech 5 polí se předají beze změny do Kroku 3.

## Krok 3: Upload binárního souboru na CDN

```http
POST https://api.premiumcdn.net/upload/ HTTP/1.1
Referer: https://prehraj.to/
User-Agent: ...
Content-Type: multipart/form-data; boundary=...

------boundary
Content-Disposition: form-data; name="nonce"

5de0ed5601ac4b6f598c6d1148fc397d
------boundary
Content-Disposition: form-data; name="params"

{"video_id":23955372,"videoId":23955372}
------boundary
Content-Disposition: form-data; name="project"

1
------boundary
Content-Disposition: form-data; name="response"

JSON
------boundary
Content-Disposition: form-data; name="signature"

3b5cd71eb41bf30acf27e6fa9e24381af9d570ea
------boundary
Content-Disposition: form-data; name="file"; filename="film.mp4"
Content-Type: video/mp4

<binary bytes>
------boundary--
```

**Pozor:** `Referer: https://prehraj.to/` je povinný, server-side guard.
Bez něj 403.

Odpověď (201 Created, JSON):

```json
{
  "files": [169094401],
  "params": "{\"video_id\":23956283,\"videoId\":23956283}",
  "signature": "d73d2eaa10bcd93a6566259771cb6153b09517b3"
}
```

- `files[0]` = numerické CDN file ID (navázané na `video_id`).
- Další `signature` — zatím nevyužíváme, ale pro případné chunked uploady
  by nejspíš sloužil pro potvrzení finalizace.

## Po uploadu

Video se v účtu zobrazí se stavem **„Zpracovává se"**. Transcoding trvá
podle velikosti:

- 2-3 kB test soubor → NESPRACUJE (Přehraj.to je ignoruje), zůstává
  „Zpracovává se" natrvalo.
- 5-10 MB → typicky hotové do 2 minut.
- 67 MB → několik minut.
- 700 MB celovečerák → ~5-15 minut.

Hotové video dostane permalink `https://prehraj.to/{slug}/{hash16}` a
embed URL `https://prehraj.to/embed/{slug}/{hash16}` (bez reklam).

### Jak získat slug + hash po uploadu

Scrape vlastního listingu:

```http
GET https://prehraj.to/profil/nahrana-videa?filterIsPrivate=1
```

V HTML jsou `<a class="... ...">Detail souboru</a>` s href ve formátu
`/{slug}/{hash16}`. Parse + match podle `name` / `video_id`.

## Persistence session

JWT `access_token` expiruje po ~10 min. `refresh_token` drží session
2 roky. Server automaticky vydává nový `access_token` v `Set-Cookie`
při requestu s platným `refresh_token`. **Cookie jar si drž napříč
všemi requesty** (`reqwest::ClientBuilder::cookie_store(true)` /
`requests.Session()`) a posílej zpět všechno co dostaneš.

Pro long-running jobs (upload 1+ GB): před každým dlouhým requestem
jeden lehký GET na `/profil`, který obnoví access_token, pak teprve
upload.

## Chyby a jejich význam

| Status | Význam | Řešení |
|--------|--------|--------|
| 302 (Location: /) | Session neplatná | Priming GET + login |
| 401 / 403 na `/profil` | access_token expirovaný, refresh nefunguje | Full relogin |
| 403 na CDN upload | Referer header chybí | Přidat `Referer: https://prehraj.to/` |
| 413 Request Entity Too Large | multipart zle složený | Check boundary |
| 400 na prepareVideo | chybějící pole | Všech 7 polí (description/name/size/type/erotic/folder/private) |

## Reference

- Funkční implementace: [../src/prehrajto_upload.py](../src/prehrajto_upload.py)
- Důvod vzniku (history): `/home/jirka/streamtape/PREHRAJTO-COMPLETE-FLOW.md`
