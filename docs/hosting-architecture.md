# Hosting architektura

**Rozhodnutí:** Projekt poběží **čistě na GitHubu**. Žádný Vercel, žádné VPS,
žádný externí hosting.

## Zvažované varianty

### Vercel (zamítnuto)

Původně zvažováno jako „prostor zdarma pro Olbrasoft TS projekty". Ale:

| Vercel Hobby (zdarma) | Hodnota |
|----------------------|---------|
| Function timeout | 10 s default, **max 60 s** |
| Fair use | **pouze osobní / nekomerční** |
| Bandwidth | 100 GB/měs |

60 s nestačí ani na download ~500 MB filmu (při 3.6 MB/s ze sktorrentu
trvá download 2-3 min). Pro celovečerní filmy v zásadě nepoužitelné.
Vercel Pro (5 min) nebo Fluid (15 min) stojí $20/měs a stejně není jistota.

### VPS / Fly.io / Railway (zamítnuto)

Funguje, ale $5+/měs. Zbytečné, když GitHub Actions dává víc zdarma.

### GitHub Actions (✅ zvoleno)

| GitHub Free | Hodnota |
|-------------|---------|
| **Public repo** | **neomezené Actions minuty** |
| **Private repo** | 2 000 min/měs (pro tenhle repo, private) |
| Runner disk | 14 GB per job (typicky ~8 GB použitelných) |
| Runner RAM | 7 GB |
| Runner CPU | 2 cores |
| Job timeout | 6 hodin |
| Concurrent jobs | 20 paralelně |

Jeden film = ~5-10 min pipeline → **200-400 filmů měsíčně zdarma** i v
privátním repu.

## Jak to funguje konkrétně

Každé spuštění workflow = **čerstvá ubuntu-latest VM**, která:

1. Naklonuje repo
2. Stáhne film ze sktorrentu do `/tmp/film.mp4` (ephemeral disk)
3. Nahraje ho na Přehraj.to (přes náš `src/prehrajto_upload.py`)
4. Commitne update `state/uploaded.json` zpět do repa
5. Zanikne (disk se smaže, včetně staženého filmu)

Takže:
- **Repo** zůstává malý (jen kód + JSON state, pár MB).
- **14 GB runner disk** je víc než dost pro stažení 1 filmu (průměr 700 MB,
  max 1.2 GB u Mission Impossible).

## Kritický bod: konektivita na sktorrent.eu

**GitHub Actions runnery běží v Microsoft Azure datacenters, typicky USA**
(East/West). Sktorrent.eu **může** geo-blokovat ne-EU IP adresy (stejně
jako Nova.cz).

### Jak ověřit

Spustit `.github/workflows/test-sktorrent-access.yml` (manuální dispatch).
Worker udělá `curl -I -o /dev/null -w "%{http_code}"` na všechny sktorrent
CDN nody (online1..online25.sktorrent.eu). Pokud vrátí 200, jde všechno
přes GitHub. Pokud 403, řešíme dál.

### Řešení, pokud je geo-block

V pořadí preference:

1. **Self-hosted runner v ČR** —
   - VM/kontejner u uživatele nebo na Olbrasoft serveru.
   - Zaregistruje se na GitHub jako runner, běží stejně jako hosted, jen
     s českou IP.
   - Celá logika workflow stejná, v `runs-on` stačí změnit na `self-hosted`.
   - Zdarma (kromě elektřiny a vlastního hardware).

2. **Oracle Cloud Free Tier ARM** v EU region (Frankfurt):
   - 4 vCPU, 24 GB RAM, 200 GB storage, 10 TB traffic/měs — **zdarma
     navždy**.
   - Spustit tam self-hosted runner, hotovo.

3. **Tunel přes `cz-web-proxy`** (PHP proxy, už exituje v Olbrasoft):
   - GitHub Actions runner v USA → HTTP request přes proxy
     `cz-web-proxy.olbrasoft.cz` → sktorrent.
   - Bandwidth navíc na PHP hostingu; podle kvóty možná ne ideální.

## Secrets a bezpečnost

GitHub Secrets na repo level:

| Secret | Popis |
|--------|-------|
| `PREHRAJTO_EMAIL` | Email k Přehraj.to účtu |
| `PREHRAJTO_PASSWORD` | Heslo k Přehraj.to účtu |

Settings → Secrets and variables → Actions → New repository secret.

## Cost estimate (měsíčně)

Scenario: 100 filmů / měsíc (průměr 700 MB).

| Zdroj | Spotřeba | Cena |
|-------|----------|------|
| GitHub Actions minuty | 100 × 8 min = 800 min | **$0** (v limitu 2000 min) |
| GitHub storage (repo) | ~5 MB (state JSON) | $0 |
| Sktorrent traffic (download) | 70 GB | $0 (jejich náklady) |
| Přehraj.to Premium (volitelně) | 159 Kč/měs | = $0 - $8 |
| GitHub Secrets | N/A | $0 |

**Celkem: $0-8/měs**, a to jen pokud chceš Přehraj.to Premium pro rychlejší upload.

## Pokud by limit 2000 min/měs začal vadit

Opce (v pořadí bezbolestnosti):

1. **Public repo** → neomezené minuty. Repo je stejně na vlastním účtu,
   nic citlivého tam není (secrets jsou oddělené). Nejjednodušší.
2. **Víc menších workflow + paralelizace** → stejný počet minut, ale
   víc filmů za hodinu reálně (do 20 paralelně).
3. **GitHub Teams** ($4/user/měs) → 3000 min místo 2000.
4. **Self-hosted runner** → neomezené minuty (běží na tvém hardware).
