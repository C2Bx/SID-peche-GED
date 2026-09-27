# Import des données de pêche de la Province Sud

Ce projet importe les cinq jeux de données dans PostgreSQL 17 ou SQL Server
`env_mer` de l'API Open Data Province Sud. Les tableaux imbriqués sont normalisés
dans `navire_moteur`, `carte_pecherie_specifique`, `campagne_frais` et
`capture_zone`. Le script télécharge d'abord un instantané complet dans
`data/raw/*.json`, puis remplit PostgreSQL uniquement depuis ces fichiers. La base
existante n'est donc pas modifiée si le téléchargement échoue.

Lors d'une nouvelle exécution, les JSON courants sont déplacés dans un dossier
daté sous `data/raw/archive/`. Les cinq instantanés précédents sont conservés.
Les types de frais sont répertoriés dans `frais`, puis associés aux campagnes
par `campagne_frais(campagne_id, frais_id, montant)`.

Les relations présentes dans les données sont garanties par des clés étrangères :
carte vers navire, campagne vers carte et capture vers campagne.

Le modèle est volontairement limité aux dix tables du schéma :
`pecheur_anonymise`, `navire_peche_anonymise`, `navire_moteur`,
`carte_pecherie_specifique`, `campagne_peche`, `frais`, `campagne_frais`,
`capture_peche`, `capture_zone` et `carroyage_peche`. Aucun référentiel
supplémentaire de cartes ou de zones n'est créé.
Le reset SQL est exécuté par Python à chaque extraction, pas par le conteneur.

Le moteur est choisi avec `DB_ENGINE=postgresql` ou `DB_ENGINE=sqlserver`.
Chaque membre du groupe peut donc utiliser son moteur sans modifier le code.

## Installation et lancement

```bash
cp .env.example .env
# Renseigner PROVINCE_SUD_API_KEY dans .env
docker compose up -d
pip install -r requirements.txt
python main.py
```

Le fichier `docker-compose.yml` reste dédié à PostgreSQL. Pour SQL Server sous
Windows, installer SQL Server (Express ou Developer), SQL Server Management
Studio et Microsoft ODBC Driver 18 for SQL Server, puis créer la base une fois :

```sql
CREATE DATABASE peche_nc;
```

Configurer ensuite `.env` avec l'authentification Windows :

```dotenv
DB_ENGINE=sqlserver
SQLSERVER_CONNECTION_STRING=Driver={ODBC Driver 18 for SQL Server};Server=localhost\SQLEXPRESS;Database=peche_nc;Trusted_Connection=yes;Encrypt=yes;TrustServerCertificate=yes
```

`localhost\SQLEXPRESS` est fréquent avec SQL Server Express. Pour une instance
par défaut, utiliser simplement `Server=localhost`. Le compte Windows qui lance
Python doit disposer des droits de création et de suppression des objets dans
la base `peche_nc`.

Pour reconstruire et remplir PostgreSQL uniquement depuis les JSON déjà
présents dans `data/raw/`, sans aucun appel à l'API ni rotation des fichiers :

```bash
python main.py --depuis-json
```

L'alias anglais `python main.py --from-json` est également disponible. La clé
`PROVINCE_SUD_API_KEY` n'est pas obligatoire dans ce mode.

Les tables feuilles, qui ne sont référencées par aucune autre table, peuvent
être reconstruites et importées seules :

```bash
python main.py capture_peche
```

Pour `navire_peche_anonymise`, `pecheur_anonymise` ou `campagne_peche`, relancer
le script sans argument afin de reconstruire ensemble toutes les relations.

Les copies JSON sont écrites progressivement dans `data/raw/`. Pour arrêter la
base, utiliser `docker compose down`; ajouter `-v` supprime volontairement son
volume persistant.

## Entrepôt décisionnel

Le script `src/DWH_peche_nc` construit la base `PecheDWH` à partir de l'ODS
`peche_nc.env_mer`. Il s'exécute dans SSMS, sur l'instance qui héberge l'ODS,
et se rejoue sans précaution : les tables sont retirées dans l'ordre inverse
des dépendances puis reconstruites.

Le modèle est une constellation : quatre tables de faits à des grains
différents, dix dimensions partagées et deux tables de pont.

| Table de faits | Grain |
|---|---|
| `FAIT_CARTE` | une carte de pêche |
| `FAIT_CAMPAGNE` | une campagne, c'est-à-dire une sortie |
| `FAIT_CAPTURE` | une espèce capturée lors d'une campagne |
| `FAIT_FRAIS` | un poste de dépense d'une campagne |

Chaque dimension porte une clé de substitution et un membre inconnu de clé
`-1`. Les faits ne contiennent donc jamais de `NULL` en clé étrangère, et
aucune jointure ne perd de lignes en silence. Les clés métier restent en
attribut pour pouvoir remonter à la source.

### Deux pièges à connaître avant d'interroger

`FAIT_CARTE` est un **agrégat** : ses mesures somment les campagnes de la
carte. Additionner `FAIT_CARTE.carte_recette` et
`FAIT_CAMPAGNE.campagne_recette` compterait deux fois le même chiffre
d'affaires. Il faut choisir le grain selon la question posée, jamais les deux
dans la même somme.

Une capture peut être déclarée sur plusieurs zones de pêche. `FAIT_CAPTURE`
n'en porte donc aucune, sans quoi la ligne — et le poids avec elle — serait
multipliée. La ventilation passe par `PONT_CAPTURE_ZONE`, qui porte un
facteur de répartition valant `1 / nb_zones` :

```sql
SELECT z.label, SUM(f.capture_poids_entier_total * p.facteur) AS poids
FROM FAIT_CAPTURE f
JOIN PONT_CAPTURE_ZONE p ON p.capture_id = f.capture_id
JOIN DIM_ZONE_PECHE   z ON z.zone_key    = p.zone_key
GROUP BY z.label;
```

Pour un total sans ventilation géographique, interroger `FAIT_CAPTURE` seule :
la somme y est déjà complète. À noter que la zone n'est renseignée que sur une
minorité des captures, ce qui limite d'autant la portée des analyses
spatiales.

### Contrôles

La fin du script compte les lignes de chaque table, mesure la part de membres
inconnus dans les faits, vérifie que les facteurs du pont somment bien à 1 par
capture, et compare `FAIT_CARTE` à la somme des campagnes correspondantes. Un
taux élevé de clés `-1` signale une jointure ratée plutôt qu'une donnée
manquante.

Les `CREATE INDEX` de la fin demandent de la mémoire. Sur une instance qui en
manque, ils attendent indéfiniment avec un `wait_type` à `RESOURCE_SEMAPHORE` ;
la requête qui permet de le diagnostiquer est en commentaire dans le script.

## Tests unitaires

```bash
pip install -r requirements-dev.txt
python -m pytest
```
