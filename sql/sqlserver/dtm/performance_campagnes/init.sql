-- ============================================================================
-- CONSTRUCTION DU DTM "dtm_performance_campagnes" dans la base "peche_nc", depuis le DWH "dwh"
-- Perimetre : performance des campagnes / sorties de peche
-- ============================================================================
--
-- EN CLAIR
--   Le DWH range l'information dans des tables separees, reliees par des cles
--   techniques (carte_key, navire_key...). Le DTM en tire des tableaux a
--   plat, directement lisibles par Power BI, sans jointure a refaire.
--
-- TROIS TABLES, A TROIS GRAINS (le grain = ce que represente UNE ligne)
--   1. dtm_performance_campagnes.DTM_PERFORMANCE_CAMPAGNE : une ligne par campagne
--
--   2. dtm_performance_campagnes.DTM_CAPTURE_CAMPAGNE     : une ligne par campagne ET par espece
--
--   3. dtm_performance_campagnes.DTM_FRAIS_CAMPAGNE       : une ligne par poste de depense
--
--
-- AVANT DE LANCER
--   Le script DWH doit avoir ete execute : ce script lit le datawarehouse
--
-- PORTEE : ce script INITIALISE le DTM. Il reconstruit tout a chaque
-- execution et ne conserve aucun historique, comme le script DWH.
-- L'alimentation incrementale prevue par le SFD reste a ecrire.
--
-- REGLES RETENUES
--   - Aucun montant n'est recalcule : on recopie ceux de la source.
--   - Une valeur non renseignee est libellee « Non renseigne » plutot que
--     laissee vide, pour que les filtres Power BI restent lisibles.
--     (Les colonnes numeriques et les dates restent a NULL : on n'invente pas
--     de valeur.)
--
-- AXE NAVIRE : INDICATIF (meme reserve que le DWH)
--   Le navire du DWH est celui AUTORISE SUR LA CARTE, pas forcement celui qui
--   a fait la campagne.
-- ============================================================================

-- Aucune instruction USE : la base est celle de SQLSERVER_CONNECTION_STRING.
SET XACT_ABORT ON;

-- Le DWH est vérifié avant tout DROP afin de conserver le DTM existant si sa
-- source technique est absente ou incomplète.
IF SCHEMA_ID('dwh') IS NULL
    THROW 51000, N'Le DWH requis pour le DTM performance_campagnes est incomplet : schéma dwh absent.', 1;

IF OBJECT_ID(N'dwh.FAIT_CAMPAGNE', N'U') IS NULL
    THROW 51001, N'Le DWH requis pour le DTM performance_campagnes est incomplet : table dwh.FAIT_CAMPAGNE absente.', 1;
IF OBJECT_ID(N'dwh.FAIT_CAPTURE', N'U') IS NULL
    THROW 51002, N'Le DWH requis pour le DTM performance_campagnes est incomplet : table dwh.FAIT_CAPTURE absente.', 1;
IF OBJECT_ID(N'dwh.FAIT_FRAIS', N'U') IS NULL
    THROW 51003, N'Le DWH requis pour le DTM performance_campagnes est incomplet : table dwh.FAIT_FRAIS absente.', 1;
IF OBJECT_ID(N'dwh.FAIT_CARTE', N'U') IS NULL
    THROW 51004, N'Le DWH requis pour le DTM performance_campagnes est incomplet : table dwh.FAIT_CARTE absente.', 1;
IF OBJECT_ID(N'dwh.DIM_CARTE', N'U') IS NULL
    THROW 51005, N'Le DWH requis pour le DTM performance_campagnes est incomplet : table dwh.DIM_CARTE absente.', 1;
IF OBJECT_ID(N'dwh.DIM_PERSONNE', N'U') IS NULL
    THROW 51006, N'Le DWH requis pour le DTM performance_campagnes est incomplet : table dwh.DIM_PERSONNE absente.', 1;
IF OBJECT_ID(N'dwh.DIM_COMMUNE', N'U') IS NULL
    THROW 51007, N'Le DWH requis pour le DTM performance_campagnes est incomplet : table dwh.DIM_COMMUNE absente.', 1;
IF OBJECT_ID(N'dwh.DIM_TEMPS', N'U') IS NULL
    THROW 51008, N'Le DWH requis pour le DTM performance_campagnes est incomplet : table dwh.DIM_TEMPS absente.', 1;
IF OBJECT_ID(N'dwh.DIM_ESPECE', N'U') IS NULL
    THROW 51009, N'Le DWH requis pour le DTM performance_campagnes est incomplet : table dwh.DIM_ESPECE absente.', 1;
IF OBJECT_ID(N'dwh.DIM_NAVIRE', N'U') IS NULL
    THROW 51010, N'Le DWH requis pour le DTM performance_campagnes est incomplet : table dwh.DIM_NAVIRE absente.', 1;
IF OBJECT_ID(N'dwh.DIM_MOTEUR', N'U') IS NULL
    THROW 51011, N'Le DWH requis pour le DTM performance_campagnes est incomplet : table dwh.DIM_MOTEUR absente.', 1;

-- On range ce DTM dans son propre schéma afin que les futurs Data Marts
-- puissent disposer chacun de leur schéma dédié.
IF SCHEMA_ID('dtm_performance_campagnes') IS NULL
    EXEC('CREATE SCHEMA dtm_performance_campagnes');
GO

BEGIN TRY
    BEGIN TRANSACTION;

    -- On supprime les anciennes versions pour pouvoir relancer le script autant de fois que necessaire.
    DROP TABLE IF EXISTS dtm_performance_campagnes.DTM_CAPTURE_CAMPAGNE;
    DROP TABLE IF EXISTS dtm_performance_campagnes.DTM_FRAIS_CAMPAGNE;
    DROP TABLE IF EXISTS dtm_performance_campagnes.DTM_PERFORMANCE_CAMPAGNE;


-- ============================================================================
-- 1. DTM_PERFORMANCE_CAMPAGNE (grain : une campagne)
-- ============================================================================
-- la table principale. On part de dwh.FAIT_CAMPAGNE et on remplace
-- les cles techniques par des informations lisibles (annee, capitaine,
-- commune...).
--
-- On n'utilise QUE les montants de FAIT_CAMPAGNE, jamais ceux de FAIT_CARTE :
-- FAIT_CARTE est le total des campagnes d'une carte, les melanger compterait
-- deux fois les memes montants.
CREATE TABLE dtm_performance_campagnes.DTM_PERFORMANCE_CAMPAGNE (
    campagne_id               VARCHAR(255)  NOT NULL PRIMARY KEY,
    carte_id                  VARCHAR(255)  NULL,

    -- Temps : la campagne est rattachee a sa date de debut
    annee                     SMALLINT      NULL,
    mois                      TINYINT       NULL,
    trimestre                 TINYINT       NULL,
    date_debut                DATE          NULL,
    date_fin                  DATE          NULL,

    -- Pecheur : le capitaine de la carte
    capitaine_id              VARCHAR(255)  NULL,
    capitaine_commune         NVARCHAR(200) NULL,
    capitaine_sexe            NVARCHAR(60)  NULL,

    -- duree_jours vaut NULL si la fin precede le debut.
    duree_jours               INT           NULL,
    jours_mer                 FLOAT         NULL,
    jours_peche               FLOAT         NULL,
    nbre_equipage             FLOAT         NULL,
    nbr_femme_abord           INT           NULL,

    -- Totaux des captures de la campagne.
    -- Aucune capture : nombre_captures = 0, les autres restent NULL.
    nombre_captures           INT           NOT NULL,
    quantite_capturee_total   FLOAT         NULL,  -- somme de capture_nombre : tres majoritairement 0, mesure complementaire V1 a valider
    poids_capture_total       FLOAT         NULL,
    valeur_captures_total     FLOAT         NULL,  -- sous reserve de validation de la coherence des valeurs

    -- Rentabilite : montants de la source
    campagne_benefice         FLOAT         NULL,
    campagne_depense          FLOAT         NULL,
    campagne_recette          FLOAT         NULL,
    campagne_rendement        FLOAT         NULL,
    campagne_carburant_qte    FLOAT         NULL,
    campagne_salaire_matelots FLOAT         NULL,
    campagne_salaire_patron   FLOAT         NULL,
    campagne_charges_sociales FLOAT         NULL
);

INSERT INTO dtm_performance_campagnes.DTM_PERFORMANCE_CAMPAGNE (
    campagne_id, carte_id,
    annee, mois, trimestre, date_debut, date_fin,
    capitaine_id, capitaine_commune, capitaine_sexe,
    duree_jours, jours_mer, jours_peche, nbre_equipage, nbr_femme_abord,
    nombre_captures, quantite_capturee_total, poids_capture_total,
    valeur_captures_total,
    campagne_benefice, campagne_depense, campagne_recette, campagne_rendement,
    campagne_carburant_qte, campagne_salaire_matelots, campagne_salaire_patron,
    campagne_charges_sociales)
SELECT
    fc.campagne_id,
    dc.carte_id,
    td.annee, td.mois, td.trimestre, td.date_id, tf.date_id,
    dp.personne_id,
    ISNULL(com.commune, N'Non renseignée'),
    ISNULL(NULLIF(dp.sexe, 'Inconnu'), N'Non renseigné'),
    fc.duree_jours, fc.campagne_jours_mer, fc.campagne_jours_peche,
    fc.campagne_nbre_equipage, fc.campagne_nbr_femme_abord,
    ISNULL(cap.nombre_captures, 0), cap.quantite_totale, cap.poids_total,
    cap.valeur_total,
    fc.campagne_benefice, fc.campagne_depense, fc.campagne_recette,
    fc.campagne_rendement, fc.campagne_carburant_qte,
    fc.campagne_salaire_matelots, fc.campagne_salaire_patron,
    fc.campagne_charges_sociales
FROM dwh.FAIT_CAMPAGNE fc
-- la carte de la campagne (pour retrouver son identifiant lisible)
LEFT JOIN dwh.DIM_CARTE    dc  ON dc.carte_key    = fc.carte_key
-- FAIT_CARTE : une seule ligne par carte, c'est lui qui connait le capitaine
LEFT JOIN dwh.FAIT_CARTE   fk  ON fk.carte_key    = fc.carte_key
LEFT JOIN dwh.DIM_PERSONNE dp  ON dp.personne_key = fk.capitaine_key
LEFT JOIN dwh.DIM_COMMUNE  com ON com.commune_key = dp.commune_key
-- deux jointures sur le calendrier : une pour le debut, une pour la fin
LEFT JOIN dwh.DIM_TEMPS    td  ON td.temps_key    = fc.temps_debut_key
LEFT JOIN dwh.DIM_TEMPS    tf  ON tf.temps_key    = fc.temps_fin_key
-- totaux des captures, calcules campagne par campagne
LEFT JOIN (
    SELECT campagne_id,
           COUNT(DISTINCT capture_id)      AS nombre_captures,
           SUM(capture_nombre)             AS quantite_totale,
           SUM(capture_poids_entier_total) AS poids_total,
           SUM(capture_valeurxpf)          AS valeur_total
    FROM dwh.FAIT_CAPTURE
    GROUP BY campagne_id
) cap ON cap.campagne_id = fc.campagne_id;


-- ============================================================================
-- 2. DTM_CAPTURE_CAMPAGNE (grain : une campagne x une espece)
-- ============================================================================
-- les captures par campagne et par espece. Les totaux de la table precedente ne donnent pas l'espece, d'ou
-- cette table : « pour telle campagne, combien de captures, quel poids, pour
-- telle espece ».
--
-- La zone de peche n'y figure pas (axe « eventuel » dans le SFD) : une capture
-- peut avoir jusqu'a 6 zones, l'ajouter multiplierait les poids. Pour une
-- analyse par zone, utiliser dwh.PONT_CAPTURE_ZONE.
CREATE TABLE dtm_performance_campagnes.DTM_CAPTURE_CAMPAGNE (
    campagne_id       VARCHAR(255)  NOT NULL,
    espece_key        INT           NOT NULL,
    categorie_code    VARCHAR(255)  NULL,
    categorie_nom     NVARCHAR(255) NULL,
    produit           NVARCHAR(400) NULL,
    annee             SMALLINT      NULL,
    mois              TINYINT       NULL,
    capitaine_id      VARCHAR(255)  NULL,
    nombre_captures   INT           NOT NULL,
    quantite_capturee FLOAT         NULL,
    poids_capture     FLOAT         NULL,
    valeur_captures   FLOAT         NULL,
    CONSTRAINT PK_DTM_CAPTURE_CAMPAGNE PRIMARY KEY (campagne_id, espece_key)
);

INSERT INTO dtm_performance_campagnes.DTM_CAPTURE_CAMPAGNE (
    campagne_id, espece_key, categorie_code, categorie_nom, produit,
    annee, mois, capitaine_id,
    nombre_captures, quantite_capturee, poids_capture, valeur_captures)
SELECT
    f.campagne_id,
    f.espece_key,
    MAX(e.categorie_code),
    ISNULL(MAX(e.categorie_nom), N'Non renseigné'),
    ISNULL(MAX(e.produit), N'Non renseigné'),
    MAX(t.annee), MAX(t.mois),
    MAX(dp.personne_id),
    COUNT(DISTINCT f.capture_id),
    SUM(f.capture_nombre),
    SUM(f.capture_poids_entier_total),
    SUM(f.capture_valeurxpf)
FROM dwh.FAIT_CAPTURE f
LEFT JOIN dwh.DIM_ESPECE   e  ON e.espece_key    = f.espece_key
LEFT JOIN dwh.DIM_TEMPS    t  ON t.temps_key     = f.temps_key
LEFT JOIN dwh.FAIT_CARTE   fk ON fk.carte_key    = f.carte_key
LEFT JOIN dwh.DIM_PERSONNE dp ON dp.personne_key = fk.capitaine_key
-- une capture sans campagne ne peut pas etre rangee « par campagne » ;
-- l'ecart eventuel apparait dans les verifications en fin de script
WHERE f.campagne_id IS NOT NULL
GROUP BY f.campagne_id, f.espece_key;


-- ============================================================================
-- 3. DTM_FRAIS_CAMPAGNE (grain : un poste de depense d'une campagne)
-- ============================================================================
--pour repondre a « a quoi sert l'argent depense ? ». Une campagne
-- apparait plusieurs fois, une fois par poste (carburant, glace, appats...).
--
-- La zone de peche n'y figure pas : elle vit au niveau de la capture, l'ajouter
-- dupliquerait les lignes de frais et fausserait les sommes de montants.
--
-- ATTENTION a la lecture : la somme des postes de frais n'est pas egale a
-- campagne_depense. Le detail des frais ne contient pas les salaires
-- (campagne_salaire_matelots, campagne_salaire_patron). Ce n'est pas une
-- anomalie.
--
-- Le carburant et la marque sont ceux du moteur principal du navire de la
-- carte (usage = 'Principale'). En cas de double motorisation, on retient le
-- premier moteur principal. Colonnes INDICATIVES (voir l'en-tete).
CREATE TABLE dtm_performance_campagnes.DTM_FRAIS_CAMPAGNE (
    campagne_id                VARCHAR(255)  NOT NULL,
    frais_id                   VARCHAR(255)  NOT NULL,
    nature_frais               NVARCHAR(255) NULL,
    montant                    FLOAT         NULL,
    annee                      SMALLINT      NULL,
    mois                       TINYINT       NULL,
    capitaine_id               VARCHAR(255)  NULL,
    jours_mer                  FLOAT         NULL,
    -- INDICATIF : navire autorise sur la carte
    navire_origine             NVARCHAR(120) NULL,
    navire_categorie_navigation NVARCHAR(120) NULL,
    navire_tranche_longueur    NVARCHAR(30)  NULL,
    navire_nb_moteurs          INT           NULL,
    marque_moteur_principal    NVARCHAR(200) NULL,
    carburant_moteur_principal NVARCHAR(60)  NULL,
    CONSTRAINT PK_DTM_FRAIS_CAMPAGNE PRIMARY KEY (campagne_id, frais_id)
);

INSERT INTO dtm_performance_campagnes.DTM_FRAIS_CAMPAGNE (
    campagne_id, frais_id, nature_frais, montant, annee, mois,
    capitaine_id, jours_mer,
    navire_origine, navire_categorie_navigation, navire_tranche_longueur,
    navire_nb_moteurs, marque_moteur_principal, carburant_moteur_principal)
SELECT
    ff.campagne_id, ff.frais_id, ff.nature_frais, ff.montant,
    t.annee, t.mois,
    dp.personne_id,
    fc.campagne_jours_mer,
    ISNULL(dn.origine, N'Non renseigné'),
    ISNULL(dn.categorie_navigation, N'Non renseigné'),
    ISNULL(NULLIF(dn.tranche_longueur, 'Inconnue'), N'Non renseigné'),
    dn.nb_moteurs,
    ISNULL(NULLIF(mp.marque, 'Inconnue'), N'Non renseigné'),
    ISNULL(NULLIF(mp.carburant, 'Inconnu'), N'Non renseigné')
FROM dwh.FAIT_FRAIS ff
-- LEFT JOIN : aucune ligne de frais ne doit disparaitre
LEFT JOIN dwh.FAIT_CAMPAGNE fc ON fc.campagne_id    = ff.campagne_id
LEFT JOIN dwh.DIM_TEMPS     t  ON t.temps_key       = ff.temps_key
LEFT JOIN dwh.FAIT_CARTE    fk ON fk.carte_key      = ff.carte_key
LEFT JOIN dwh.DIM_PERSONNE  dp ON dp.personne_key   = fk.capitaine_key
LEFT JOIN dwh.DIM_NAVIRE    dn ON dn.navire_key     = ff.navire_key
-- moteur principal : on classe les moteurs de chaque navire (le principal en
-- premier) et on ne garde que le premier
LEFT JOIN (
    SELECT navire_key, marque, carburant,
           ROW_NUMBER() OVER (
               PARTITION BY navire_key
               ORDER BY CASE WHEN usage_moteur = 'Principale' THEN 0 ELSE 1 END,
                        moteur_key) AS rang
    FROM dwh.DIM_MOTEUR
) mp ON mp.navire_key = ff.navire_key AND mp.rang = 1;

    COMMIT TRANSACTION;
END TRY
BEGIN CATCH
    IF @@TRANCOUNT > 0
        ROLLBACK TRANSACTION;

    THROW;
END CATCH;


-- ============================================================================
-- 4. VERIFICATIONS
-- ============================================================================

SELECT 'DTM_PERFORMANCE_CAMPAGNE / FAIT_CAMPAGNE' AS controle,
       (SELECT COUNT(*) FROM dtm_performance_campagnes.DTM_PERFORMANCE_CAMPAGNE) AS dtm,
       (SELECT COUNT(*) FROM dwh.FAIT_CAMPAGNE)            AS dwh
UNION ALL
SELECT 'DTM_FRAIS_CAMPAGNE / FAIT_FRAIS',
       (SELECT COUNT(*) FROM dtm_performance_campagnes.DTM_FRAIS_CAMPAGNE),
       (SELECT COUNT(*) FROM dwh.FAIT_FRAIS)
UNION ALL
SELECT 'DTM_CAPTURE_CAMPAGNE : captures / FAIT_CAPTURE (avec campagne)',
       (SELECT SUM(nombre_captures) FROM dtm_performance_campagnes.DTM_CAPTURE_CAMPAGNE),
       (SELECT COUNT(*) FROM dwh.FAIT_CAPTURE WHERE campagne_id IS NOT NULL);

--  les sommes doivent aussi etre identiques. Une jointure qui
-- duplique des lignes gonflerait les montants sans faire d'erreur.
SELECT (SELECT SUM(montant) FROM dtm_performance_campagnes.DTM_FRAIS_CAMPAGNE) AS frais_dtm,
       (SELECT SUM(montant) FROM dwh.FAIT_FRAIS)         AS frais_dwh;

SELECT (SELECT SUM(campagne_recette) FROM dtm_performance_campagnes.DTM_PERFORMANCE_CAMPAGNE) AS recette_dtm,
       (SELECT SUM(campagne_recette) FROM dwh.FAIT_CAMPAGNE)            AS recette_dwh;

SELECT (SELECT SUM(poids_capture_total) FROM dtm_performance_campagnes.DTM_PERFORMANCE_CAMPAGNE) AS poids_perf_dtm,
       (SELECT SUM(poids_capture)       FROM dtm_performance_campagnes.DTM_CAPTURE_CAMPAGNE)     AS poids_capture_dtm,
       (SELECT SUM(capture_poids_entier_total) FROM dwh.FAIT_CAPTURE)      AS poids_dwh;

-- le benefice doit valoir recette - depense. Un ecart
-- n'est PAS corrige : la valeur de la source est conservee, l'ecart est
-- signale pour analyse avec les metiers.
SELECT COUNT(*) AS campagnes_en_ecart
FROM dtm_performance_campagnes.DTM_PERFORMANCE_CAMPAGNE
WHERE campagne_benefice IS NOT NULL
  AND campagne_recette  IS NOT NULL
  AND campagne_depense  IS NOT NULL
  AND ABS(campagne_benefice - (campagne_recette - campagne_depense)) > 1;

-- combien de campagnes n'ont pas pu etre rattachees a un capitaine
-- ou a une date. Un taux eleve signale un probleme de jointure en amont.
SELECT SUM(CASE WHEN capitaine_id IS NULL THEN 1 ELSE 0 END) AS sans_capitaine,
       SUM(CASE WHEN annee IS NULL        THEN 1 ELSE 0 END) AS sans_date_debut,
       COUNT(*) AS total
FROM dtm_performance_campagnes.DTM_PERFORMANCE_CAMPAGNE;
