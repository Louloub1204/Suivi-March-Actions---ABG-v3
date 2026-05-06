# Outil SVM — Application Streamlit

Application web qui automatise le fichier Excel **Outil_SVM.xlsx** pour la
gestion des 24 Fonds Communs de Placement (FCP) cotés sur la BRVM.

## Architecture

- **Front-end** : Streamlit Cloud (gratuit)
- **Base de données** : Postgres hébergée chez Supabase (gratuit jusqu'à 500 Mo)
- **Code source** : GitHub (privé)
- **Authentification** : page de login simple (mot de passe partagé via Streamlit Secrets)

## Setup initial (une seule fois)

### 1. Créer la base Postgres sur Supabase

1. Aller sur [supabase.com](https://supabase.com), créer un compte gratuit.
2. **New Project** → choisir un nom (ex : `svm-outil`), une région (Frankfurt
   pour la latence Sénégal/Europe), un mot de passe pour la base.
3. Une fois le projet créé, aller dans **Project Settings → Database →
   Connection string → URI**. Copier la chaîne, qui ressemble à :
   ```
   postgresql://postgres.[ref]:[password]@aws-0-eu-central-1.pooler.supabase.com:6543/postgres
   ```

### 2. Charger les données initiales

Sur ton ordinateur, en local :

```bash
git clone https://github.com/<your-username>/svm-outil
cd svm-outil
pip install -r requirements.txt

export DATABASE_URL='postgresql://postgres...'  # la chaîne copiée ci-dessus
python seed_postgres.py
```

Le script crée le schéma puis charge les ~6 100 transactions et ~149 000 cours
historiques. Compte 30-60 secondes.

### 3. Configurer les Streamlit Secrets

Sur https://share.streamlit.io, ouvrir ton app → **Settings → Secrets**.
Copier-coller :

```toml
[db]
url = "postgresql://postgres.[ref]:[password]@aws-0-eu-central-1.pooler.supabase.com:6543/postgres"

[auth]
password = "le-mot-de-passe-que-tu-veux-pour-l-app"
```

Sauvegarder. Streamlit redéploie automatiquement.

### 4. Tester

Ouvrir l'URL Streamlit. Une page de login apparaît, entrer le mot de passe.
Vérifier dans **⚙️ Paramètres** que les compteurs sont bien remplis.

## Modules

| Module | Fonction |
| --- | --- |
| 📈 **Tableau de bord** | Positions, CMP, valorisation, ± value, **P&L journalier corrigé** (poche détenue + poche trades de la période, frais inclus). |
| 📊 **Récap variations** | Tableau unique des 24 FCPs avec variation jour et YTD. |
| 💼 **Transactions** | Saisie ACHAT / VENTE par formulaire. **Bouton SharePoint** qui télécharge `PTF ACTIONS CGF GESTION v2.xlsm` et écrase les transactions. |
| 🌐 **Cours BRVM** | Bouton « Rafraîchir » qui scrape sikafinance.com (fallback brvm.org). |
| 📚 **Historique cours** | Tracé interactif. **Bouton SharePoint** qui écrase tout l'historique des cours depuis la feuille Cours du fichier CGF. |
| ⚙️ **Paramètres** | Statut de la base, gestion des dividendes par titre. |

## Fichiers

```
svm_app/
├── app.py                # UI Streamlit (6 pages)
├── auth.py               # Page de login (mot de passe partagé)
├── portfolio.py          # Moteur de calcul P&L
├── fcp_calendar.py       # Mapping FCP → jour de valorisation
├── db.py                 # Couche Postgres (SQLAlchemy)
├── scraper.py            # Scraper sikafinance / brvm.org
├── sharepoint_sync.py    # Téléchargement du fichier CGF GESTION
├── seed_postgres.py      # Script CLI de chargement initial des données
├── seed_data/            # Données initiales (transactions, cours, FCPs)
└── requirements.txt
```

## Sauvegardes

Supabase fait des backups quotidiens automatiques sur le tier gratuit.
Pour un export manuel à un instant T :

1. Dashboard Supabase → **Project → Database → Backups**
2. Ou bien via l'interface SQL : exporter en CSV chaque table

Les CSV de seed initiaux dans `seed_data/` sont aussi une copie figée des
données du fichier Excel d'origine (avril 2026), à garder par sécurité.
