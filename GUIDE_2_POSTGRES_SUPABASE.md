# Guide de déploiement — Partie 2 : Postgres (Supabase)

## Vue d'ensemble

Ce guide explique comment :
1. Créer la base de données Postgres sur Supabase (gratuit)
2. Récupérer la chaîne de connexion
3. Peupler la base depuis ton ordinateur (seed initial)
4. Vérifier que tout fonctionne

---

## ÉTAPE 1 — Créer le projet Supabase

1. Va sur https://supabase.com → **Start your project**
2. Connecte-toi avec ton compte GitHub (le plus simple)
3. Clique **New project**
4. Remplis :
   - **Organization** : ton compte personnel (ou CGF BOURSE)
   - **Name** : `svm-outil`
   - **Database Password** : clique **Generate a password**
     ⚠️ IMPORTANT : copie ce mot de passe et sauvegarde-le quelque part
     (gestionnaire de mots de passe, note sécurisée)
     Il ne sera plus affiché après
   - **Region** : `West EU (Ireland)` ou `Central EU (Frankfurt)`
   - **Pricing plan** : Free
5. Clique **Create new project**
6. Attends 2-3 minutes que la base s'initialise

---

## ÉTAPE 2 — Récupérer la chaîne de connexion

1. Une fois le projet créé, clique sur le bouton **Connect**
   (en haut de la page d'accueil du projet, bouton vert/bleu)

2. Dans la fenêtre qui s'ouvre, clique sur l'onglet **Direct**
   (intitulé "Connection string")

3. Dans le menu déroulant, sélectionne **Transaction pooler**

4. Tu vois une chaîne comme :
   ```
   postgresql://postgres.abcdefghij:[YOUR-PASSWORD]@aws-1-eu-west-3.pooler.supabase.com:6543/postgres
   ```

5. Copie cette chaîne et **remplace `[YOUR-PASSWORD]`** par le mot de passe
   que tu as généré à l'étape 1

6. Vérifie que la chaîne finale a :
   - Le mot `pooler` dans le hostname ✓
   - Le port `6543` (pas 5432) ✓
   - Un seul `@` entre le mot de passe et le hostname ✓

⚠️ Si ton mot de passe contient des caractères spéciaux (@, #, :, /, &, +),
ils doivent être encodés :
- `@` → `%40`
- `#` → `%23`
- `:` → `%3A`
- `/` → `%2F`
- `&` → `%26`
- `+` → `%2B`

Conseil : si tu as ce problème, réinitialise le mot de passe avec uniquement
des lettres et chiffres (ex: `SvmCgfBourse2026`).

---

## ÉTAPE 3 — Peupler la base (seed initial)

Cette étape se fait **depuis ton ordinateur**, une seule fois.
Elle charge les ~149 000 cours historiques, 6 100 transactions, et 24 FCPs.

### Prérequis

- Python installé sur ton ordinateur
  (vérifie avec `python --version` dans un terminal)
- Le dossier `svm_app/` dézippé sur ton ordinateur

### Sur Mac/Linux

Ouvre Terminal et tape :

```bash
# Navigue vers le dossier svm_app
cd /chemin/vers/svm_app

# Installe les dépendances
pip install -r requirements.txt

# Configure l'URL de connexion
export DATABASE_URL='postgresql://postgres.XXXX:MOTDEPASSE@aws-1-eu-west-3.pooler.supabase.com:6543/postgres'

# Lance le seed
python seed_postgres.py
```

### Sur Windows (PowerShell)

Ouvre PowerShell (pas PowerShell ISE) et tape :

```powershell
# Navigue vers le dossier svm_app
cd "C:\chemin\vers\svm_app"

# Installe les dépendances
pip install -r requirements.txt

# Configure l'URL de connexion
$env:DATABASE_URL='postgresql://postgres.XXXX:MOTDEPASSE@aws-1-eu-west-3.pooler.supabase.com:6543/postgres'

# Lance le seed
python seed_postgres.py
```

### Résultat attendu

```
→ Création du schéma…
→ Chargement des données depuis seed_data/…
==================================================
  ✓ 24 FCPs
  ✓ 6 100 transactions
  ✓ 149 251 cours archivés
  ✓ 47 cours du jour
==================================================
Base prête. Tu peux déployer l'app sur Streamlit Cloud.
```

L'opération prend 1 à 3 minutes selon ta connexion.

### Erreurs courantes

| Message | Solution |
|---|---|
| `password authentication failed` | Mauvais mot de passe ou caractères spéciaux non encodés |
| `connection refused` | Mauvaise URL — vérifie le hostname et le port 6543 |
| `ModuleNotFoundError: sqlalchemy` | Relance `pip install -r requirements.txt` |
| `DATABASE_URL not defined` | La variable n'est pas définie — refais l'export/set |
| Timeout après 2 min | Réseau lent — relance, le script reprend là où il s'est arrêté |

---

## ÉTAPE 4 — Configurer les Secrets Streamlit

Une fois la base peuplée, configure Streamlit pour qu'il s'y connecte.

1. Va sur https://share.streamlit.io
2. Trouve ton app → **3 points** → **Settings** → onglet **Secrets**
3. Colle :

```toml
[db]
url = "postgresql://postgres.XXXX:MOTDEPASSE@aws-1-eu-west-3.pooler.supabase.com:6543/postgres"

[auth]
password = "MotDePasseUtilisateurs"
```

4. **Save** → l'app redémarre automatiquement

---

## ÉTAPE 5 — Vérification

1. Ouvre l'URL de ton app Streamlit
2. Une page de login apparaît → entre le mot de passe `[auth] password`
3. Va dans **⚙️ Paramètres** → tu dois voir :
   ```
   FCPs : 24
   Transactions : 6 100
   Cours archivés : 149 251
   ```
4. Va dans **📈 Tableau de bord** → sélectionne `FCP PLACEMENT CROISSANCE`
   → la valorisation doit s'afficher (~2,6 milliards FCFA au 28/04/2026)

Si tout s'affiche → l'app est opérationnelle ✓

---

## Sauvegardes Supabase

Supabase fait des backups automatiques quotidiens sur le tier gratuit.

Pour un export manuel :
1. Dashboard Supabase → **SQL Editor**
2. Lance : `SELECT * FROM transactions` → Export CSV
3. Ou depuis le **Table Editor** → chaque table peut être exportée en CSV

---

## Limites du tier gratuit Supabase

| Ressource | Limite | Ton usage estimé |
|---|---|---|
| Stockage | 500 Mo | ~50 Mo (OK) |
| Requêtes/mois | 50 000 | ~5 000 (OK) |
| Connexions simultanées | 60 (pooler) | <5 (OK) |
| Pause après inactivité | 7 jours sans connexion | Non applicable (usage quotidien) |

⚠️ Si le projet Supabase se met en pause (7 jours sans utilisation),
l'app affichera une erreur de connexion. Pour le réactiver :
Dashboard Supabase → ton projet → bouton **Restore project**.

---

## Quand passer à l'Option B (VPS) ?

Je te notifierai si je vois un de ces signes :
- Stockage Supabase > 200 Mo
- Temps de réponse du Récap > 5 secondes
- Besoins d'authentification multi-utilisateurs avec rôles
- Usage > 30 000 requêtes/mois (approche de la limite gratuite)

Pour l'instant Supabase + Streamlit Cloud couvre largement ton usage.
