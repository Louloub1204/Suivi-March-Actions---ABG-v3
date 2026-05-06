# Guide de déploiement — Partie 1 : GitHub + Streamlit Cloud

## Vue d'ensemble

```
Ton ordinateur (code + seed_data)
        ↓ upload
GitHub (repo privé)
        ↓ déploiement auto
Streamlit Cloud (interface web)
        ↓ lit/écrit
Supabase Postgres (base de données)
```

---

## ÉTAPE 1 — Créer le repo GitHub

1. Va sur https://github.com → connecte-toi
2. Clique sur **+** (haut à droite) → **New repository**
3. Remplis :
   - **Repository name** : `svm-outil` (sans espaces)
   - **Visibility** : ⚫ **Private**
   - ❌ Ne coche RIEN dans "Initialize this repository"
4. Clique **Create repository**
5. Garde la page ouverte — tu en auras besoin à l'étape suivante

---

## ÉTAPE 2 — Uploader les fichiers sur GitHub

### Activer l'affichage des fichiers cachés (important !)

**Mac** : dans le Finder, appuie sur **Cmd + Shift + .** (point)
**Windows** : Explorateur → Affichage → cocher **Éléments masqués**

Tu dois voir apparaître `.gitignore` et le dossier `.streamlit`.

### Uploader à la racine du repo

1. Sur la page GitHub "Quick setup", clique sur **uploading an existing file**
2. Ouvre le dossier `svm_app/` sur ton ordinateur
3. Sélectionne **tous les fichiers et dossiers** sauf `seed_data/`
   - app.py, auth.py, auto_sync.py, db.py, fcp_calendar.py
   - portfolio.py, requirements.txt, scraper.py, sectors.py
   - seed_postgres.py, sharepoint_sync.py, README.md
   - .gitignore
   - .streamlit/ (dossier entier)
4. Glisse-les dans la zone GitHub
5. Message de commit : `Initial commit`
6. **Commit changes**
7. Attends que l'upload se termine (~30 secondes)

### Uploader le dossier seed_data

GitHub ne supporte pas l'upload de dossiers directement.
Il faut naviguer dans le dossier puis uploader les fichiers.

1. Sur GitHub, dans ton repo, clique sur **Add file → Create new file**
2. Dans le champ "Name your file", tape : `seed_data/fcps.json`
   (GitHub créera automatiquement le dossier `seed_data/`)
3. Reviens en arrière
4. Maintenant clique sur le dossier `seed_data/` qui vient d'apparaître
5. **Add file → Upload files**
6. Glisse les 5 fichiers du dossier `seed_data/` de ton ordinateur :
   - cours.csv, fcps.json, sectors.json, table4.csv, transactions.csv
7. Message : `Add seed data`
8. **Commit changes**

### Vérification finale sur GitHub

Tu dois voir à la racine du repo :
```
.streamlit/
seed_data/
.gitignore
README.md
app.py
auth.py
auto_sync.py
db.py
fcp_calendar.py
portfolio.py
requirements.txt
scraper.py
sectors.py
seed_postgres.py
sharepoint_sync.py
```

---

## ÉTAPE 3 — Déployer sur Streamlit Cloud

1. Va sur https://share.streamlit.io → **Sign in → Continue with GitHub**
2. Autorise Streamlit à accéder à tes repos privés
3. Clique **Create app** → **Deploy a public app from GitHub**
4. Remplis :
   - **Repository** : `ton-username/svm-outil`
   - **Branch** : `main`
   - **Main file path** : `app.py`
   - **App URL** (optionnel) : `svm-cgf` → donnera `svm-cgf.streamlit.app`
5. **Ne clique pas encore sur Deploy** → continue à l'étape 4

---

## ÉTAPE 4 — Configurer les Secrets AVANT le déploiement

Avant de lancer le déploiement, configure les secrets :

1. Sur la page de déploiement Streamlit, clique sur **Advanced settings**
2. Clique sur l'onglet **Secrets**
3. Colle exactement ceci :

```toml
[db]
url = "postgresql://postgres.XXXX:MOTDEPASSE@aws-1-eu-west-3.pooler.supabase.com:6543/postgres"

[auth]
password = "MotDePasseDeConnexionApp"
```

Remplace :
- `XXXX` par l'identifiant de ton projet Supabase
- `MOTDEPASSE` par le mot de passe de ta base Postgres
- `MotDePasseDeConnexionApp` par le mot de passe que les utilisateurs verront

⚠️ L'URL Postgres vient de Supabase (voir Guide Partie 2 pour créer la base).

4. **Save** → puis clique **Deploy!**

---

## ÉTAPE 5 — Premier déploiement

Le build prend 3 à 5 minutes (installation de pandas, SQLAlchemy, etc.).
Tu verras les logs défiler. À la fin, l'app s'ouvre.

⚠️ Au premier lancement, l'app affichera :
```
RuntimeError: Aucune URL de base de données configurée
```
Si les Secrets sont mal configurés.

Si c'est le cas → retourne dans Settings → Secrets → vérifie le format.

---

## ÉTAPE 6 — Peupler la base de données (OBLIGATOIRE)

L'app est déployée mais la base Postgres est vide. Il faut la peupler depuis
ton ordinateur avec le script `seed_postgres.py`.

Voir **Guide Partie 2 — Postgres** pour cette étape.

---

## Mises à jour futures

Quand tu veux modifier le code :
1. Sur GitHub, ouvre le fichier à modifier
2. Clique sur ✏️ (crayon)
3. Modifie et commit
4. Streamlit redéploie automatiquement dans la minute

Pour uploader plusieurs fichiers d'un coup :
→ **Add file → Upload files** depuis la racine du repo

---

## En cas d'erreur

| Message | Cause | Solution |
|---|---|---|
| `RuntimeError: Aucune URL` | Secrets manquants | Ajoute `[db] url = ...` dans Settings → Secrets |
| `ImportError: cannot import` | Mauvais fichier uploadé | Ré-uploade le fichier concerné |
| `password authentication failed` | Mauvais mot de passe Postgres | Réinitialise le mot de passe dans Supabase |
| App vide / aucun FCP | Base non peuplée | Lance `python seed_postgres.py` |
| `Module not found` | requirements.txt pas uploadé | Vérifie que requirements.txt est à la racine |
