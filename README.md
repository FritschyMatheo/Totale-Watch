# Total Watch — suivi des ruptures / réapprovisionnements

Surveille des stations TotalEnergies choisies (Rouffach, Mulhouse, Mulhouse→Cernay)
à partir du flux open data prix-carburants.gouv.fr, et affiche par carburant
(Diesel, ou Essence SP95-E10 / SP98) : disponible ou en rupture, et un journal
des fins de rupture (= réapprovisionnements).

## Mise en place (une fois, ~5 min)

1. Créer un dépôt GitHub (public, pour GitHub Pages gratuit) et y pousser ce dossier.
2. **Settings → Actions → General → Workflow permissions** : cocher
   « Read and write permissions » (le workflow commite les données).
3. **Settings → Pages** : Source = « Deploy from a branch », branche `main`, dossier `/ (root)`.
4. **Actions** → workflow « Relevé carburants » → **Run workflow** pour le premier relevé.
   Ensuite il tourne seul toutes les 10 min.
5. La page est servie sur `https://<utilisateur>.github.io/<dépôt>/`.

## Fichiers

- `stations.json` — stations suivies (id du flux gouvernemental). À éditer pour ajouter/retirer.
- `collect.py` — collecteur : interroge l'API, détecte début/fin de rupture, écrit `data/`.
- `.github/workflows/collect.yml` — cron GitHub Actions toutes les 10 min.
- `index.html` — interface statique (lit `data/latest.json` et `data/events.json`).
- `tests/` — réponses API sauvegardées : `python3 collect.py --from tests/api_2026-09-11.json`.

## Limites connues

- Le flux instantané ne liste que les ruptures en cours : une fin de rupture est datée
  du relevé qui constate sa disparition (±10 min, plus le retard éventuel du cron GitHub).
- Les ruptures sont déclarées par l'exploitant ; une station qui ne déclare rien apparaît « disponible ».
- GitHub désactive les crons d'un dépôt sans activité depuis 60 jours ; les commits du bot comptent comme activité.
- Alertes (e-mail / Telegram) : point d'extension `notify()` dans `collect.py`, vide en v1.
"# Totale-Watch" 
