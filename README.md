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

Par défaut, cette commande exécute le workflow complet : téléchargement
(ou lecture JSON), reconstruction et contrôles de l'ODS `env_mer`, puis
construction du DWH `dwh` dans la même base `peche_nc`.

```bash
python main.py                    # API -> ODS -> DWH -> DTM
python main.py --ods-only         # API -> ODS uniquement
python main.py --dwh-only         # env_mer existant -> DWH -> DTM
python main.py --dtm-only         # DWH existant -> DTM uniquement
python main.py --depuis-json      # JSON existants -> ODS -> DWH -> DTM
python main.py --depuis-json --ods-only  # JSON existants -> ODS uniquement
```

Le mode `--dwh-only` n'appelle pas l'API et ne requiert donc pas
`PROVINCE_SUD_API_KEY`. Il reconstruit aussi les DTM, qui lisent le DWH et
seraient sinon désynchronisés. Les options `--ods-only`, `--dwh-only` et
`--dtm-only` sont mutuellement exclusives.

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

Les copies JSON sont écrites progressivement dans `data/raw/`. Pour arrêter la
base, utiliser `docker compose down`; ajouter `-v` supprime volontairement son
volume persistant.

## Entrepôt décisionnel

Le DWH est construit dans le schéma `dwh` de la base `peche_nc`, à partir de
l'ODS `env_mer`. Python orchestre uniquement le script correspondant au moteur :

- `sql/postgresql/dwh/init_dwh.sql` pour PostgreSQL ;
- `sql/sqlserver/dwh/init_dwh.sql` pour SQL Server.

Ces scripts sont la référence du modèle métier et reconstruisent les 17 tables,
leurs données, ponts, index et contrôles. Sur SQL Server, les lignes `GO` sont
traitées comme des séparateurs de batches par le runner Python.

Il **initialise** le DWH. Reconstruisant tout à chaque exécution, il ne
conserve aucun historique : ni date d'intégration, ni distinction entre
lignes nouvelles, modifiées et inchangées. L'alimentation incrémentale prévue
par le SFD reste à écrire, et ce script ne convient pas aux chargements
courants.

Le modèle est une constellation : quatre tables de faits à des grains
différents, onze dimensions partagées et deux tables de pont.

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

Le détail de la motorisation vit dans `DIM_MOTEUR`, rattachée au navire :
certains navires portent plusieurs moteurs, et n'en retenir qu'un perdrait
l'information. `DIM_NAVIRE` ne garde que `nb_moteurs`.

### L'axe navire est indicatif

Les faits portent un `navire_key` dérivé de
`pecheur_anonymise.carte_autorisation_navire_id`. Cette colonne désigne le
navire **autorisé sur la carte**, et non celui qui a réellement effectué la
campagne. Le SFD constate qu'aucune relation fiable entre pêcheurs et navires
n'existe dans les sources, et met hors périmètre V1 les indicateurs qui en
dépendent — frais d'entretien par navire, navires par pêcheur, rentabilité
par navire.

L'axe est conservé pour ne pas perdre l'information, mais toute restitution
par navire doit rappeler cette limite.

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

La fin du script enchaîne cinq contrôles :

- le nombre de lignes de chaque table ;
- la part de membres inconnus dans les faits — quelques `-1` sont normaux, un
  taux élevé signale une jointure ratée plutôt qu'une donnée manquante ;
- les captures posées sur `technique_key = -1` **alors que leur combinaison
  existe en dimension**. En SQL, `NULL = NULL` n'est pas vrai : une jointure
  qui n'anticipe pas ce cas écarte les combinaisons dont un membre est nul, et
  la capture tombe sur l'inconnu à tort ;
- le grain de `DIM_PERSONNE`, qui doit être strictement la personne : un
  doublon y ferait enfler la jointure de `FAIT_CARTE` jusqu'à violer sa clé
  primaire ;
- la somme des facteurs du pont, qui doit valoir 1 par capture ventilée, et
  l'écart entre `FAIT_CARTE` et la somme des campagnes correspondantes.

Ces quatre derniers renvoient `0` quand tout va bien. Le runner Python
journalise chaque résultat (`Contrôle SQL : personnes_en_double=0`, …) sans
interrompre le pipeline : un écart reste à lire dans les logs.

Les `CREATE INDEX` de la fin demandent de la mémoire. Sur une instance qui en
manque, ils attendent indéfiniment avec un `wait_type` à `RESOURCE_SEMAPHORE` ;
la requête qui permet de le diagnostiquer est en commentaire dans le script.

## Tests unitaires

```bash
pip install -r requirements-dev.txt
python -m pytest
```

## Restitution HTML

`reporting/` calcule les **17 indicateurs** de la fiche « Indicateurs de la
restitution » et les publie dans une page HTML autonome :
`reporting/performance_campagnes/index.html`. Chaque fonction de
`reporting/indicateurs.py` reproduit la mesure DAX de référence de la fiche
(numéro d'indicateur en docstring) et lit le DWH `dwh` et le DTM
`dtm_performance_campagnes`, sur PostgreSQL comme sur SQL Server.

| Thème | Indicateurs |
|---|---|
| Sociologique | 3.1.1 pêcheurs actifs · 3.1.2 évolution, âge, genre, commune · 3.1.3 expérience · 3.1.4 capitaines et patrons |
| Matériel | 3.2.1 navires · 3.2.2 âge de la flotte · 3.2.4 motorisation (3.2.3 et 3.2.5 exclus par le SFD) |
| Environnemental | 3.3.1 captures par mois · 3.3.2 par espèce · 3.3.3 par zone |
| Activité | 3.4.1 campagnes par mois · 3.4.2 durée · 3.4.3 captures par campagne · 3.4.4 campagnes actives |
| Économique | 3.5.1 par pêcheur · 3.5.2 par campagne · 3.5.3 coûts (3.5.4 exclu par le SFD) |

La restitution n'affiche **aucune donnée brute** : uniquement des indicateurs
et des agrégats, sans identifiant de pêcheur, de campagne ou de capture. La
liste des campagnes actives (3.4.4) n'est proposée qu'en export CSV, à côté de
la page. Les hypothèses de la fiche (pêcheur = capitaine, tranches d'âge, seuil
de 1950…) sont rappelées dans la page.

### Actualisation

La restitution suit le contenu de la base :

- `python main.py`, `--dwh-only` et `--dtm-only` la **régénèrent
  automatiquement** après les DTM (`--sans-rapport` pour s'en passer). Après
  un ajout dans les sources, `python main.py --dwh-only` reconstruit le DWH,
  les DTM puis la page.
- `python -m reporting.build_report --watch` **surveille** le DWH et les DTM
  (nombre de lignes de chaque table lue, toutes les 30 s par défaut) et
  régénère la page dès qu'une donnée change ; la page ouverte se recharge
  seule. `Ctrl+C` arrête la surveillance.

```bash
python -m reporting.build_report                        # depuis la base (.env)
python -m reporting.build_report --date-ref 2025-12-31  # date de référence (défaut : aujourd'hui)
python -m reporting.build_report --watch 60             # surveillance toutes les 60 s
python -m reporting.build_report --demo                 # données fictives, sans base
python -m reporting.build_report --plotly inline        # fichier utilisable hors ligne
```

| Fichier | Rôle |
|---|---|
| `reporting/data.py` | requêtes DWH/DTM, empreinte de la base, jeu de démonstration |
| `reporting/indicateurs.py` | calcul des indicateurs, une fonction par mesure de la fiche |
| `reporting/restitution.py` | regroupement en thèmes, textes, hypothèses |
| `reporting/charts.py` | graphiques Plotly et charte |
| `reporting/templates/` | gabarits Jinja2 de la page |
| `reporting/build_report.py` | ligne de commande, export CSV, surveillance |
