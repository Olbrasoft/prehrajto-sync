# Backlog

Sem přijde seznam filmů ze sktorrent.eu, které nejsou ještě na našem Přehraj.to
účtu. Uživatel ho generuje v oddělené session (ke dni 2026-04-18 má 9 254
kandidátů, 15.9 % verified).

## Očekávaný formát

Placeholder (JSONL nebo JSON array, rozhodne se podle toho co uživatel dodá):

```jsonl
{"id": 56413, "title": "Lví král", "year": 1994, "quality": "720p", "url": "https://online8.sktorrent.eu/media/videos//h264/56413_720p.mp4"}
{"id": 19988, "title": "Umění létat 3D", "year": 2011, "quality": "720p", "url": "https://online11.sktorrent.eu/media/videos//h264/19988_720p.mp4"}
```

## Zatím nic

Až uživatel dodá první dávku, uložíme sem jako `sktorrent-films.jsonl`
a `src/check_missing.py` z ní bude číst.
