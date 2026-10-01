from flask import Flask, render_template, request, redirect, url_for, send_file, flash, send_from_directory
import sqlite3
from zk import ZK
import threading
import time
import os
from datetime import date, datetime
from flask_login import (
    LoginManager, login_required, login_user, logout_user,
    current_user
)

from Rapports_pdf import generer_pdf_rapport
from auth import (
    Utilisateur, initialiser_tables_auth, verifier_identifiants,
    get_utilisateur_par_id, get_tous_comptes_employes,
    creer_ou_mettre_a_jour_compte_employe, reinitialiser_mdp_employe,
    get_compte_admin, modifier_compte_admin
)
from horaires import (
    initialiser_table_horaires, get_horaire_employe,
    enregistrer_programme_initial, modifier_programme,
    soumettre_demande_modification, traiter_demande_horaire,
    basculer_autorisation_modification, get_tous_horaires_employes,
    get_demandes_en_attente
)

app = Flask(__name__, static_folder='static')
app.secret_key = "gestion_absences_pointeuse_2024_secret_key_zk_rh"

# Route PWA : sert le Service Worker depuis la racine (scope /)
@app.route('/sw.js')
def service_worker():
    response = send_from_directory(app.static_folder, 'sw.js')
    response.headers['Service-Worker-Allowed'] = '/'
    response.headers['Cache-Control'] = 'no-cache'
    return response

@app.context_processor
def injecter_globales_horaires():
    try:
        nb_dem = len(get_demandes_en_attente())
    except Exception:
        nb_dem = 0
    return {"nb_demandes_horaires": nb_dem}

# ---------- Flask-Login ----------
login_manager = LoginManager(app)
login_manager.login_view = "login"
login_manager.login_message = "Veuillez vous connecter pour accéder à cette page."
login_manager.login_message_category = "info"

@login_manager.user_loader
def charger_utilisateur(user_id):
    return get_utilisateur_par_id(user_id)


IP = "192.168.1.201"
PORT = 4370
INTERVALLE_SYNC_SECONDES = 15  # Détection automatique dès branchement

TYPES_POINTAGE = {
    0: "arrivée",
    1: "départ",
    4: "arrivée",
    5: "départ"
}

# État global de synchronisation en temps réel
etat_synchronisation = {
    "connectee": False,
    "derniere_sync_heure": None,
    "nb_nouveaux_pointages": 0,
    "message": "En attente de connexion à la pointeuse...",
    "erreur": None
}

# ---------- Fonctions utilitaires ----------

def calculer_duree_secondes(arrivee_str, depart_str):
    if not arrivee_str or not depart_str:
        return 0
    try:
        t1 = datetime.strptime(arrivee_str, "%H:%M:%S")
        t2 = datetime.strptime(depart_str, "%H:%M:%S")
        diff = (t2 - t1).total_seconds()
        return max(0, diff)
    except Exception:
        return 0


def formater_secondes(sec):
    if sec <= 0:
        return "0m"
    h = int(sec // 3600)
    m = int((sec % 3600) // 60)
    if h > 0:
        return f"{h}h {m:02d}m"
    return f"{m}m"


def get_liste_services():
    conn = sqlite3.connect("gestion_absences.db")
    cur = conn.cursor()
    cur.execute("SELECT DISTINCT service FROM employes WHERE service IS NOT NULL AND TRIM(service) != '' ORDER BY service")
    services = [row[0] for row in cur.fetchall()]
    conn.close()
    return services


# ---------- Fonctions base de données ----------

def get_presences(date_filtre=None, employe_filtre=None):
    """
    Récupère les présences. Garde l'historique complet de TOUS les employés
    (actifs ou anciens), sans jamais supprimer les pointages passés.
    """
    conn = sqlite3.connect("gestion_absences.db")
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    requete = """
        SELECT presences.id, presences.date, presences.heure_arrivee, presences.heure_depart,
               presences.statut,
               employes.id AS employe_id, employes.nom, employes.service, employes.actif,
               COALESCE(h.type_programme, employes.type_programme, 'jour') AS type_programme,
               COALESCE(h.heure_debut, employes.heure_debut_prevue, '08:00') AS heure_debut_prevue,
               COALESCE(h.heure_fin, employes.heure_fin_prevue, '16:00') AS heure_fin_prevue
        FROM presences
        JOIN employes ON presences.employe_id = employes.id
        LEFT JOIN horaires_employes h ON employes.id = h.employe_id
        WHERE 1=1
    """
    params = []

    if date_filtre:
        requete += " AND presences.date = ?"
        params.append(date_filtre)

    if employe_filtre:
        requete += " AND employes.id = ?"
        params.append(employe_filtre)

    requete += " ORDER BY presences.date DESC, employes.nom ASC"

    cur.execute(requete, params)
    resultats = cur.fetchall()
    conn.close()
    return resultats


def get_employes_actifs():
    conn = sqlite3.connect("gestion_absences.db")
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute("SELECT id, nom, service, actif FROM employes WHERE actif = 1 ORDER BY nom")
    resultats = cur.fetchall()
    conn.close()
    return resultats


def get_tous_employes():
    conn = sqlite3.connect("gestion_absences.db")
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute("SELECT id, nom, service, actif FROM employes ORDER BY nom")
    resultats = cur.fetchall()
    conn.close()
    return resultats


def desactiver_employe(employe_id):
    conn = sqlite3.connect("gestion_absences.db")
    cur = conn.cursor()
    cur.execute("UPDATE employes SET actif = 0 WHERE id = ?", (employe_id,))
    conn.commit()
    conn.close()

    zk = ZK(IP, port=PORT, timeout=30, password=0, force_udp=False, ommit_ping=False)
    conn_pointeuse = None
    try:
        conn_pointeuse = zk.connect()
        users = conn_pointeuse.get_users()
        for u in users:
            if str(u.user_id) == str(employe_id):
                conn_pointeuse.delete_user(uid=u.uid)
                print(f"Utilisateur {employe_id} supprimé de la pointeuse.")
                break
    except Exception as e:
        print(f"Note : utilisateur {employe_id} désactivé en base mais pointeuse inaccessible : {e}")
    finally:
        if conn_pointeuse:
            try:
                conn_pointeuse.disconnect()
            except Exception:
                pass


def reactiver_employe(employe_id):
    conn = sqlite3.connect("gestion_absences.db")
    cur = conn.cursor()
    cur.execute("UPDATE employes SET actif = 1 WHERE id = ?", (employe_id,))
    conn.commit()
    conn.close()


def _upsert_compte_employe_cur(cur, employe_id, nom_employe):
    """
    Version interne de creer_ou_mettre_a_jour_compte_employe() qui réutilise
    un curseur existant au lieu d'ouvrir une nouvelle connexion SQLite.
    Évite le 'database is locked' quand appelé depuis synchroniser_pointeuse()
    qui tient déjà une connexion ouverte en écriture.
    """
    from werkzeug.security import generate_password_hash
    from datetime import datetime as _dt
    DOMAINE = "entreprise.com"
    mdp = f"empreinte{employe_id}"
    email = f"{nom_employe}@{DOMAINE}"

    cur.execute("SELECT id FROM utilisateurs WHERE employe_id = ?", (employe_id,))
    existe = cur.fetchone()
    if not existe:
        cur.execute("""
            INSERT INTO utilisateurs (identifiant, email, mot_de_passe_hash, mot_de_passe_clair, role, employe_id, date_creation)
            VALUES (?, ?, ?, ?, 'employe', ?, ?)
        """, (
            nom_employe, email,
            generate_password_hash(mdp), mdp,
            employe_id,
            _dt.now().strftime("%Y-%m-%d %H:%M:%S")
        ))
    else:
        cur.execute("""
            UPDATE utilisateurs SET identifiant = ?, email = ? WHERE id = ?
        """, (nom_employe, email, existe[0]))


def synchroniser_pointeuse():
    """
    Se connecte à la pointeuse, importe tous les employés et pointages bruts.
    Gère la détection automatique dès que l'appareil est branché.
    """
    global etat_synchronisation
    conn_db = sqlite3.connect("gestion_absences.db")
    cur = conn_db.cursor()

    zk = ZK(IP, port=PORT, timeout=4, password=1324, force_udp=False, ommit_ping=False)
    conn_pointeuse = None
    nb_nouveaux = 0

    try:
        conn_pointeuse = zk.connect()
        etat_synchronisation["connectee"] = True
        etat_synchronisation["erreur"] = None

        users = conn_pointeuse.get_users()
        ids_pointeuse = {str(u.user_id) for u in users}

        for u in users:
            cur.execute("""
                INSERT INTO employes (id, nom, service, actif)
                VALUES (?, ?, NULL, 1)
                ON CONFLICT(id) DO UPDATE SET actif = 1, nom = excluded.nom
            """, (u.user_id, u.name))
            # Utilise le curseur existant pour éviter une 2e connexion SQLite
            # (qui causerait un 'database is locked')
            try:
                _upsert_compte_employe_cur(cur, u.user_id, u.name)
            except Exception as e_compte:
                print(f"Erreur création compte pour {u.user_id}: {e_compte}")

        if len(ids_pointeuse) > 0:
            cur.execute("SELECT id FROM employes WHERE actif = 1")
            ids_db_actifs = {str(row[0]) for row in cur.fetchall()}
            for employe_id in ids_db_actifs - ids_pointeuse:
                cur.execute("UPDATE employes SET actif = 0 WHERE id = ?", (employe_id,))
                print(f"Employé {employe_id} désactivé (supprimé de la pointeuse).")

        attendances = conn_pointeuse.get_attendance()
        for a in attendances:
            type_pointage = TYPES_POINTAGE.get(a.punch, "inconnu")
            cur.execute("""
                SELECT id FROM pointages WHERE employe_id = ? AND date_heure = ?
            """, (a.user_id, str(a.timestamp)))
            if not cur.fetchone():
                cur.execute("""
                    INSERT INTO pointages (employe_id, date_heure, type)
                    VALUES (?, ?, ?)
                """, (a.user_id, str(a.timestamp), type_pointage))
                nb_nouveaux += 1

        conn_db.commit()
        maintenant = datetime.now().strftime("%H:%M:%S")
        etat_synchronisation["derniere_sync_heure"] = maintenant
        etat_synchronisation["nb_nouveaux_pointages"] = nb_nouveaux
        etat_synchronisation["message"] = f"Synchronisé à {maintenant} ({len(users)} employés, {nb_nouveaux} pointage(s) ajouté(s))"
        print(f"[{maintenant}] Synchro réussie : {nb_nouveaux} nouveaux pointages.")
        return True, etat_synchronisation["message"]

    except Exception as e:
        etat_synchronisation["connectee"] = False
        etat_synchronisation["erreur"] = str(e)
        etat_synchronisation["message"] = f"Pointeuse en attente de connexion (IP: {IP})"
        return False, str(e)

    finally:
        if conn_pointeuse:
            try:
                conn_pointeuse.disconnect()
            except Exception:
                pass
        conn_db.close()


def generer_presences():
    """
    Règle automatique et inviolable :
    - Premier pointage du jour = heure d'arrivée réelle certifiée pointeuse
    - Dernier pointage du jour = heure de départ réelle certifiée pointeuse
    - Statut déterminé automatiquement selon l'horaire officiel de chaque employé :
      * Cours du jour : retard si arrivée > heure_debut prévue (ex: 08:00:00)
      * Cours du soir : retard si arrivée > heure_debut prévue (ex: 17:00:00)
    - Les heures de pointage réelles ne sont JAMAIS modifiables manuellement.
    """
    conn = sqlite3.connect("gestion_absences.db")
    cur = conn.cursor()

    cur.execute("""
        SELECT p.employe_id,
               date(p.date_heure)      AS date_str,
               MIN(time(p.date_heure)) AS heure_arrivee,
               CASE WHEN MIN(time(p.date_heure)) != MAX(time(p.date_heure))
                    THEN MAX(time(p.date_heure)) ELSE NULL END AS heure_depart,
               COALESCE(h.heure_debut, e.heure_debut_prevue, '08:00') AS heure_debut_prevue
        FROM pointages p
        LEFT JOIN employes e ON p.employe_id = e.id
        LEFT JOIN horaires_employes h ON p.employe_id = h.employe_id
        GROUP BY p.employe_id, date(p.date_heure)
    """)
    jours = cur.fetchall()

    for employe_id, date_str, heure_arrivee, heure_depart, heure_debut_prevue in jours:
        limite = (heure_debut_prevue or "08:00").strip()
        if len(limite) == 5:
            limite_complete = f"{limite}:00"
        else:
            limite_complete = limite

        if heure_arrivee and heure_arrivee > limite_complete:
            statut = "en retard"
        elif heure_arrivee:
            statut = "présent"
        else:
            statut = "absent"

        cur.execute("""
            SELECT id FROM presences
            WHERE employe_id = ? AND date = ?
        """, (employe_id, date_str))
        existing = cur.fetchone()

        if not existing:
            cur.execute("""
                INSERT INTO presences (employe_id, date, heure_arrivee, heure_depart, statut)
                VALUES (?, ?, ?, ?, ?)
            """, (employe_id, date_str, heure_arrivee, heure_depart, statut))
        else:
            cur.execute("""
                UPDATE presences
                SET heure_arrivee = ?, heure_depart = ?, statut = ?
                WHERE id = ?
            """, (heure_arrivee, heure_depart, statut, existing[0]))

    conn.commit()
    conn.close()


# ---------- Module de reporting ----------

def get_donnees_rapport(type_periode="mensuel", date_jour=None, mois=None, annee=None, date_debut=None, date_fin=None, service_filtre=None, employe_filtre=None):
    """
    Génère toutes les données et statistiques pour le rapport d'assiduité :
    - Filtre par période (journalier, mensuel, annuel, libre)
    - Filtre par département / service
    - Filtre par collaborateur
    - Calcule heures travaillées, pourcentages d'arrivée à l'heure, départs pointés, synthèse par personne.
    """
    conn = sqlite3.connect("gestion_absences.db")
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    requete = """
        SELECT presences.id, presences.date, presences.heure_arrivee, presences.heure_depart,
               presences.statut,
               employes.id AS employe_id, employes.nom, employes.service, employes.actif
        FROM presences
        JOIN employes ON presences.employe_id = employes.id
        WHERE 1=1
    """
    params = []

    # 1. Filtre Période
    titre_periode = ""
    if type_periode == "journalier":
        if not date_jour:
            date_jour = date.today().isoformat()
        requete += " AND presences.date = ?"
        params.append(date_jour)
        try:
            d_obj = datetime.strptime(date_jour, "%Y-%m-%d")
            titre_periode = d_obj.strftime("Journée du %d/%m/%Y")
        except Exception:
            titre_periode = f"Journée du {date_jour}"

    elif type_periode == "mensuel":
        if not mois:
            mois = date.today().strftime("%Y-%m")
        requete += " AND strftime('%Y-%m', presences.date) = ?"
        params.append(mois)
        try:
            d_obj = datetime.strptime(mois, "%Y-%m")
            noms_mois = ["Janvier", "Février", "Mars", "Avril", "Mai", "Juin", "Juillet", "Août", "Septembre", "Octobre", "Novembre", "Décembre"]
            titre_periode = f"{noms_mois[d_obj.month - 1]} {d_obj.year}"
        except Exception:
            titre_periode = f"Mois {mois}"

    elif type_periode == "annuel":
        if not annee:
            annee = str(date.today().year)
        requete += " AND strftime('%Y', presences.date) = ?"
        params.append(str(annee))
        titre_periode = f"Année {annee}"

    elif type_periode == "libre":
        if date_debut:
            requete += " AND presences.date >= ?"
            params.append(date_debut)
        if date_fin:
            requete += " AND presences.date <= ?"
            params.append(date_fin)  # ← manquait : le ? n'avait pas de valeur associée
        d_deb = date_debut if date_debut else "début"
        d_fin = date_fin if date_fin else "aujourd'hui"
        titre_periode = f"Du {d_deb} au {d_fin}"
    else:
        titre_periode = "Toutes les dates"

    # 2. Filtre Département / Service
    nom_service = "Tous les départements"
    if service_filtre:
        requete += " AND employes.service = ?"
        params.append(service_filtre)
        nom_service = service_filtre

    # 3. Filtre Collaborateur
    nom_employe = "Tous les collaborateurs"
    if employe_filtre:
        requete += " AND employes.id = ?"
        params.append(employe_filtre)

    requete += " ORDER BY presences.date DESC, employes.nom ASC"
    cur.execute(requete, params)
    lignes_brutes = cur.fetchall()

    if employe_filtre:
        cur.execute("SELECT nom, service FROM employes WHERE id = ?", (employe_filtre,))
        emp_row = cur.fetchone()
        if emp_row:
            nom_employe = emp_row["nom"]

    conn.close()

    total_presences = len(lignes_brutes)
    total_retards = sum(1 for l in lignes_brutes if l["statut"] == "en retard")
    total_a_l_heure = total_presences - total_retards
    total_departs_pointes = sum(1 for l in lignes_brutes if l["heure_depart"])
    total_secondes = 0

    lignes_detail = []
    employes_dict = {}

    for l in lignes_brutes:
        sec = calculer_duree_secondes(l["heure_arrivee"], l["heure_depart"])
        total_secondes += sec

        duree_str = formater_secondes(sec) if l["heure_depart"] else "–"

        lignes_detail.append({
            "id": l["id"],
            "date": l["date"],
            "employe_id": l["employe_id"],
            "nom": l["nom"],
            "service": l["service"],
            "heure_arrivee": l["heure_arrivee"],
            "heure_depart": l["heure_depart"],
            "duree_secondes": sec,
            "duree_formatee": duree_str,
            "statut": l["statut"]
        })

        eid = l["employe_id"]
        if eid not in employes_dict:
            employes_dict[eid] = {
                "id": eid,
                "nom": l["nom"],
                "service": l["service"],
                "nb_presences": 0,
                "nb_a_l_heure": 0,
                "nb_retards": 0,
                "nb_departs": 0,
                "secondes": 0
            }

        employes_dict[eid]["nb_presences"] += 1
        if l["statut"] == "en retard":
            employes_dict[eid]["nb_retards"] += 1
        else:
            employes_dict[eid]["nb_a_l_heure"] += 1

        if l["heure_depart"]:
            employes_dict[eid]["nb_departs"] += 1
        employes_dict[eid]["secondes"] += sec

    synthese_employes = []
    for e in sorted(employes_dict.values(), key=lambda x: x["nom"]):
        e["heures_str"] = formater_secondes(e["secondes"])
        e["pct_ponctualite"] = round((e["nb_a_l_heure"] / e["nb_presences"] * 100), 1) if e["nb_presences"] > 0 else 0
        e["pct_departs"] = round((e["nb_departs"] / e["nb_presences"] * 100), 1) if e["nb_presences"] > 0 else 0
        synthese_employes.append(e)

    pct_a_l_heure = round((total_a_l_heure / total_presences * 100), 1) if total_presences > 0 else 0
    pct_retards = round((total_retards / total_presences * 100), 1) if total_presences > 0 else 0
    pct_departs = round((total_departs_pointes / total_presences * 100), 1) if total_presences > 0 else 0

    stats_globales = {
        "total_presences": total_presences,
        "total_a_l_heure": total_a_l_heure,
        "total_retards": total_retards,
        "total_departs_pointes": total_departs_pointes,
        "total_secondes": total_secondes,
        "total_heures_formatees": formater_secondes(total_secondes),
        "pourcentage_a_l_heure": pct_a_l_heure,
        "pourcentage_retards": pct_retards,
        "pourcentage_departs": pct_departs,
    }

    return {
        "titre_periode": titre_periode,
        "nom_service": nom_service,
        "nom_employe": nom_employe,
        "stats_globales": stats_globales,
        "synthese_employes": synthese_employes,
        "lignes_detail": lignes_detail
    }


# ---------- Synchronisation automatique en arrière-plan ----------

def boucle_synchronisation_auto():
    while True:
        try:
            succes, _ = synchroniser_pointeuse()
            if succes:
                generer_presences()
        except Exception as e:
            print(f"Erreur arrière-plan : {e}")
        time.sleep(INTERVALLE_SYNC_SECONDES)


def demarrer_synchronisation_auto():
    thread = threading.Thread(target=boucle_synchronisation_auto, daemon=True)
    thread.start()


# ---------- Routes d'authentification ----------

@app.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        if current_user.is_admin:
            return redirect(url_for("accueil"))
        else:
            return redirect(url_for("espace_employe"))

    if request.method == "POST":
        identifiant = request.form.get("identifiant", "").strip()
        mot_de_passe = request.form.get("mot_de_passe", "")
        role_souhaite = request.form.get("role_souhaite", "").strip()
        next_url = request.form.get("next", "")

        resultat = verifier_identifiants(identifiant, mot_de_passe, role_requis=role_souhaite or None)

        if resultat == "desactive":
            flash("Votre compte a été désactivé par l'administrateur. Veuillez contacter les RH.", "erreur")
        elif resultat is None:
            if role_souhaite == "employe":
                flash("Identifiant ou mot de passe incorrect. Rappel : utilisez votre nom sur la pointeuse (ex: Anselme) et 'empreinte' + votre ID (ex: empreinte1).", "erreur")
            elif role_souhaite == "admin":
                flash("Identifiant ou mot de passe administrateur incorrect.", "erreur")
            else:
                flash("Identifiant ou mot de passe incorrect. Réessayez.", "erreur")
        else:
            login_user(resultat)
            if resultat.is_admin:
                return redirect(next_url or url_for("accueil"))
            else:
                return redirect(url_for("espace_employe"))

    next_url = request.args.get("next", "")
    return render_template("login.html", next_url=next_url)


@app.route("/logout")
def logout():
    logout_user()
    flash("Vous avez été déconnecté avec succès.", "info")
    return redirect(url_for("login"))


@app.route("/mon-espace")
@login_required
def espace_employe():
    """Page personnelle de l'employé : ses taux de présence, retard et assiduité."""
    if current_user.is_admin:
        return redirect(url_for("accueil"))

    employe_id = current_user.employe_id
    mois_selectionne = request.args.get("mois", "").strip()

    conn = sqlite3.connect("gestion_absences.db")
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    # Récupérer tous les mois disponibles pour l'employé
    cur.execute("""
        SELECT DISTINCT strftime('%Y-%m', date) AS mois_val
        FROM presences
        WHERE employe_id = ?
        ORDER BY mois_val DESC
    """, (employe_id,))
    mois_disponibles = [row["mois_val"] for row in cur.fetchall()]

    noms_mois_fr = ["Janvier", "Février", "Mars", "Avril", "Mai", "Juin",
                    "Juillet", "Août", "Septembre", "Octobre", "Novembre", "Décembre"]
    liste_mois = []
    for mv in mois_disponibles:
        try:
            d_obj = datetime.strptime(mv, "%Y-%m")
            libelle = f"{noms_mois_fr[d_obj.month - 1]} {d_obj.year}"
        except Exception:
            libelle = mv
        liste_mois.append({"valeur": mv, "libelle": libelle})

    # Requête de base pour les présences de l'employé
    requete = "SELECT id, date, heure_arrivee, heure_depart, statut FROM presences WHERE employe_id = ?"
    params = [employe_id]

    if mois_selectionne and mois_selectionne != "tout":
        requete += " AND strftime('%Y-%m', date) = ?"
        params.append(mois_selectionne)
        # Titre période
        try:
            d_obj = datetime.strptime(mois_selectionne, "%Y-%m")
            titre_periode = f"{noms_mois_fr[d_obj.month - 1]} {d_obj.year}"
        except Exception:
            titre_periode = mois_selectionne
    else:
        mois_selectionne = "tout"
        titre_periode = "Historique complet"

    requete += " ORDER BY date DESC"
    cur.execute(requete, params)
    presences_brutes = cur.fetchall()
    conn.close()

    # Calcul des statistiques personnelles
    nb_presences = len(presences_brutes)
    nb_a_l_heure = sum(1 for p in presences_brutes if p["statut"] == "présent")
    nb_retards = sum(1 for p in presences_brutes if p["statut"] == "en retard")
    total_secondes = sum(
        calculer_duree_secondes(p["heure_arrivee"], p["heure_depart"])
        for p in presences_brutes
    )

    taux_ponctualite = round((nb_a_l_heure / nb_presences * 100), 1) if nb_presences > 0 else 0
    taux_retard = round((nb_retards / nb_presences * 100), 1) if nb_presences > 0 else 0

    # Taux d'assiduité : nb de jours pointés sur les jours ouvrés de la période
    if mois_selectionne != "tout" and mois_selectionne:
        import calendar
        try:
            d_obj = datetime.strptime(mois_selectionne, "%Y-%m")
            nb_jours_cal = calendar.monthrange(d_obj.year, d_obj.month)[1]
            # On compte les jours ouvrés (lundi-vendredi) du mois
            jours_ouvres = sum(
                1 for j in range(1, nb_jours_cal + 1)
                if datetime(d_obj.year, d_obj.month, j).weekday() < 5
            )
        except Exception:
            jours_ouvres = 22
    else:
        jours_ouvres = nb_presences  # Sur tout l'historique, on ramène à 100%

    taux_assiduite = round((nb_presences / jours_ouvres * 100), 1) if jours_ouvres > 0 else 0

    # Heures moyennes par journée pointée
    nb_jours_avec_depart = sum(1 for p in presences_brutes if p["heure_depart"])
    moyenne_secondes = (total_secondes / nb_jours_avec_depart) if nb_jours_avec_depart > 0 else 0

    # Construire la liste des présences avec la durée formatée
    presences_detail = []
    for p in presences_brutes:
        sec = calculer_duree_secondes(p["heure_arrivee"], p["heure_depart"])
        presences_detail.append({
            "id": p["id"],
            "date": p["date"],
            "heure_arrivee": p["heure_arrivee"],
            "heure_depart": p["heure_depart"],
            "statut": p["statut"],
            "duree_formatee": formater_secondes(sec) if p["heure_depart"] else None
        })

    stats = {
        "titre_periode": titre_periode,
        "nb_presences": nb_presences,
        "nb_a_l_heure": nb_a_l_heure,
        "nb_retards": nb_retards,
        "taux_ponctualite": taux_ponctualite,
        "taux_retard": taux_retard,
        "taux_assiduite": min(100, taux_assiduite),
        "jours_ouvres_attendus": jours_ouvres,
        "heures_totales_str": formater_secondes(total_secondes),
        "moyenne_heures_str": formater_secondes(moyenne_secondes)
    }

    horaire = get_horaire_employe(employe_id)

    return render_template(
        "espace_employe.html",
        stats=stats,
        presences=presences_detail,
        liste_mois=liste_mois,
        mois_selectionne=mois_selectionne,
        horaire=horaire
    )


# ---------- Routes de Gestion des Horaires (Cours de Jour & Soir) ----------

@app.route("/configurer_programme_initial", methods=["POST"])
@login_required
def route_configurer_programme_initial():
    """
    Première connexion : l'employé configure ses horaires (journée ou cours du soir).
    Enregistre en base et recalcule automatiquement les présences avec ses horaires.
    """
    if current_user.is_admin:
        return redirect(url_for("accueil"))

    type_programme = request.form.get("type_programme", "jour").strip()
    heure_debut = request.form.get("heure_debut", "08:00").strip()
    heure_fin = request.form.get("heure_fin", "16:00").strip()
    jours_semaine = request.form.get("jours_semaine", "Lundi-Vendredi").strip()

    enregistrer_programme_initial(
        current_user.employe_id,
        type_programme,
        heure_debut,
        heure_fin,
        jours_semaine
    )
    # Recalcul automatique avec les nouveaux horaires
    generer_presences()

    flash("Votre programme de travail a été enregistré avec succès ! Vos présences et calculs d'assiduité sont désormais personnalisés selon vos horaires.", "succes")
    return redirect(url_for("espace_employe"))


@app.route("/modifier_mon_programme", methods=["POST"])
@login_required
def route_modifier_mon_programme():
    """
    Modification autonome par l'employé (uniquement si l'admin lui a accordé l'autorisation).
    """
    if current_user.is_admin:
        return redirect(url_for("accueil"))

    type_programme = request.form.get("type_programme", "jour").strip()
    heure_debut = request.form.get("heure_debut", "08:00").strip()
    heure_fin = request.form.get("heure_fin", "16:00").strip()
    jours_semaine = request.form.get("jours_semaine", "Lundi-Vendredi").strip()

    succes, message = modifier_programme(
        current_user.employe_id,
        type_programme,
        heure_debut,
        heure_fin,
        jours_semaine,
        par_admin=False
    )

    if succes:
        generer_presences()
        flash(message, "succes")
    else:
        flash(message, "erreur")

    return redirect(url_for("espace_employe"))


@app.route("/demander_modification_programme", methods=["POST"])
@login_required
def route_demander_modification_programme():
    """
    Demande de modification d'horaires soumise à la direction par l'employé sans autorisation directe.
    """
    if current_user.is_admin:
        return redirect(url_for("accueil"))

    type_programme = request.form.get("type_programme", "jour").strip()
    heure_debut = request.form.get("heure_debut", "17:00").strip()
    heure_fin = request.form.get("heure_fin", "21:00").strip()
    jours_semaine = request.form.get("jours_semaine", "Lundi-Vendredi").strip()
    motif = request.form.get("motif", "").strip()

    soumettre_demande_modification(
        current_user.employe_id,
        type_programme,
        heure_debut,
        heure_fin,
        jours_semaine,
        motif
    )

    flash("Votre demande de modification d'horaires a été transmise avec succès à l'administration.", "succes")
    return redirect(url_for("espace_employe"))


@app.route("/programmes_horaires")
@login_required
def route_programmes_horaires():
    """
    Page Admin : Visualisation et gestion complète des horaires de chaque collaborateur,
    gestion des cours du jour et cours du soir, et traitement des demandes en attente.
    """
    if not current_user.is_admin:
        flash("Accès réservé à l'administrateur.", "erreur")
        return redirect(url_for("espace_employe"))

    employes_horaires = get_tous_horaires_employes()
    demandes = get_demandes_en_attente()

    return render_template(
        "programmes.html",
        employes_horaires=employes_horaires,
        demandes=demandes,
        etat_sync=etat_synchronisation
    )


@app.route("/admin/modifier_programme/<int:employe_id>", methods=["POST"])
@login_required
def route_admin_modifier_programme(employe_id):
    """
    Admin : modifie directement le programme d'un collaborateur
    (selon le programme papier/officiel fourni).
    """
    if not current_user.is_admin:
        flash("Accès réservé à l'administrateur.", "erreur")
        return redirect(url_for("espace_employe"))

    type_programme = request.form.get("type_programme", "jour").strip()
    heure_debut = request.form.get("heure_debut", "08:00").strip()
    heure_fin = request.form.get("heure_fin", "16:00").strip()
    jours_semaine = request.form.get("jours_semaine", "Lundi-Vendredi").strip()

    succes, message = modifier_programme(
        employe_id,
        type_programme,
        heure_debut,
        heure_fin,
        jours_semaine,
        par_admin=True
    )
    generer_presences()
    flash(f"Programme de l'employé #{employe_id} mis à jour avec succès.", "succes")
    return redirect(request.referrer or url_for("route_programmes_horaires"))


@app.route("/admin/toggle_autorisation_programme/<int:employe_id>", methods=["POST"])
@login_required
def route_admin_toggle_autorisation(employe_id):
    """
    Admin : accorde ou révoque le droit de modification autonome pour un employé.
    """
    if not current_user.is_admin:
        flash("Accès réservé à l'administrateur.", "erreur")
        return redirect(url_for("espace_employe"))

    nouvel_etat = basculer_autorisation_modification(employe_id)
    if nouvel_etat:
        flash(f"Autorisation de modification d'horaires accordée à l'employé #{employe_id}.", "succes")
    else:
        flash(f"Autorisation révoquée : l'employé #{employe_id} ne peut plus modifier directement ses horaires.", "info")

    return redirect(request.referrer or url_for("route_programmes_horaires"))


@app.route("/admin/traiter_demande_programme/<int:employe_id>/<string:action>", methods=["POST"])
@login_required
def route_admin_traiter_demande(employe_id, action):
    """
    Admin : accepte ou refuse une demande de changement d'horaires formulée par un employé.
    """
    if not current_user.is_admin:
        flash("Accès réservé à l'administrateur.", "erreur")
        return redirect(url_for("espace_employe"))

    succes, message = traiter_demande_horaire(employe_id, action)
    if action == "accepter":
        generer_presences()
        flash(message, "succes")
    else:
        flash(message, "info")

    return redirect(request.referrer or url_for("route_programmes_horaires"))


@app.route("/comptes_employes")
@login_required
def route_comptes_employes():
    """Page admin : liste des comptes employés avec email et mot de passe temporaire."""
    if not current_user.is_admin:
        flash("Accès réservé à l'administrateur.", "erreur")
        return redirect(url_for("espace_employe"))

    comptes = get_tous_comptes_employes()
    admin_compte = get_compte_admin()
    return render_template(
        "comptes.html",
        comptes=comptes,
        admin_compte=admin_compte,
        etat_sync=etat_synchronisation
    )


@app.route("/modifier_compte_admin", methods=["POST"])
@login_required
def route_modifier_compte_admin():
    """Permet à l'administrateur de modifier son identifiant, son email et son mot de passe."""
    if not current_user.is_admin:
        flash("Accès réservé à l'administrateur.", "erreur")
        return redirect(url_for("espace_employe"))

    identifiant = request.form.get("identifiant", "").strip()
    email = request.form.get("email", "").strip()
    nouveau_mdp = request.form.get("nouveau_mot_de_passe", "").strip()
    confirmer_mdp = request.form.get("confirmer_mot_de_passe", "").strip()

    if nouveau_mdp:
        if len(nouveau_mdp) < 4:
            flash("Le mot de passe doit comporter au moins 4 caractères.", "erreur")
            return redirect(url_for("route_comptes_employes"))
        if nouveau_mdp != confirmer_mdp:
            flash("Les deux mots de passe saisis ne correspondent pas.", "erreur")
            return redirect(url_for("route_comptes_employes"))

    succes, message = modifier_compte_admin(identifiant, email, nouveau_mdp if nouveau_mdp else None)
    flash(message, "succes" if succes else "erreur")
    return redirect(url_for("route_comptes_employes"))


@app.route("/reinitialiser_mdp_employe/<int:compte_id>", methods=["POST"])
@login_required
def route_reinitialiser_mdp(compte_id):
    """Admin : réinitialise le mot de passe d'un employé à empreinte + ID."""
    if not current_user.is_admin:
        return redirect(url_for("espace_employe"))
    reinitialiser_mdp_employe(compte_id)
    flash("Mot de passe réinitialisé avec succès.", "succes")
    return redirect(url_for("route_comptes_employes"))



# ---------- Routes (pages du site) ----------

@app.route("/")
@login_required
def accueil():
    if not current_user.is_admin:
        return redirect(url_for("espace_employe"))

    date_filtre = request.args.get("date", "").strip()
    employe_filtre = request.args.get("employe", "").strip()

    presences = get_presences(date_filtre or None, employe_filtre or None)
    employes = get_employes_actifs()
    tous_employes = get_tous_employes()

    employe_selectionne = None
    if employe_filtre:
        for e in tous_employes:
            if str(e["id"]) == str(employe_filtre):
                employe_selectionne = e
                break

    aujourd_hui = date.today().isoformat()

    return render_template(
        "index.html",
        presences=presences,
        employes=employes,
        tous_employes=tous_employes,
        date_filtre=date_filtre,
        employe_filtre=employe_filtre,
        employe_selectionne=employe_selectionne,
        aujourd_hui=aujourd_hui,
        etat_sync=etat_synchronisation
    )


@app.route("/desactiver/<int:employe_id>", methods=["POST"])
@login_required
def route_desactiver(employe_id):
    if not current_user.is_admin:
        return redirect(url_for("espace_employe"))
    desactiver_employe(employe_id)
    return redirect(request.referrer or url_for("accueil"))


@app.route("/reactiver/<int:employe_id>", methods=["POST"])
@login_required
def route_reactiver(employe_id):
    if not current_user.is_admin:
        return redirect(url_for("espace_employe"))
    reactiver_employe(employe_id)
    return redirect(request.referrer or url_for("accueil"))


@app.route("/modifier_service/<int:employe_id>", methods=["POST"])
@login_required
def route_modifier_service(employe_id):
    if not current_user.is_admin:
        return redirect(url_for("espace_employe"))
    service = request.form.get("service", "").strip() or None
    conn = sqlite3.connect("gestion_absences.db")
    cur = conn.cursor()
    cur.execute("UPDATE employes SET service = ? WHERE id = ?", (service, employe_id))
    conn.commit()
    conn.close()
    return redirect(request.referrer or url_for("accueil"))


@app.route("/synchroniser", methods=["POST"])
@login_required
def route_synchroniser():
    if not current_user.is_admin:
        return redirect(url_for("espace_employe"))
    succes, msg = synchroniser_pointeuse()
    if succes:
        generer_presences()
    return redirect(request.referrer or url_for("accueil"))


@app.route("/rapports")
@login_required
def route_rapports():
    if not current_user.is_admin:
        return redirect(url_for("espace_employe"))
    type_periode = request.args.get("type_periode", "mensuel").strip()
    date_jour    = request.args.get("date_jour", date.today().isoformat()).strip()
    mois         = request.args.get("mois", date.today().strftime("%Y-%m")).strip()
    annee        = request.args.get("annee", str(date.today().year)).strip()
    date_debut   = request.args.get("date_debut", "").strip()
    date_fin     = request.args.get("date_fin", "").strip()
    service      = request.args.get("service", "").strip()
    employe      = request.args.get("employe", "").strip()

    donnees = get_donnees_rapport(
        type_periode=type_periode,
        date_jour=date_jour,
        mois=mois,
        annee=annee,
        date_debut=date_debut,
        date_fin=date_fin,
        service_filtre=service or None,
        employe_filtre=employe or None
    )

    services = get_liste_services()
    tous_employes = get_tous_employes()

    params = {
        "type_periode": type_periode,
        "date_jour": date_jour,
        "mois": mois,
        "annee": annee,
        "date_debut": date_debut,
        "date_fin": date_fin,
        "service": service,
        "employe": employe
    }

    return render_template(
        "rapports.html",
        donnees=donnees,
        services=services,
        tous_employes=tous_employes,
        params=params,
        etat_sync=etat_synchronisation
    )


@app.route("/rapports/pdf")
@login_required
def route_rapports_pdf():
    if not current_user.is_admin:
        return redirect(url_for("espace_employe"))
    type_periode = request.args.get("type_periode", "mensuel").strip()
    date_jour    = request.args.get("date_jour", date.today().isoformat()).strip()
    mois         = request.args.get("mois", date.today().strftime("%Y-%m")).strip()
    annee        = request.args.get("annee", str(date.today().year)).strip()
    date_debut   = request.args.get("date_debut", "").strip()
    date_fin     = request.args.get("date_fin", "").strip()
    service      = request.args.get("service", "").strip()
    employe      = request.args.get("employe", "").strip()

    donnees = get_donnees_rapport(
        type_periode=type_periode,
        date_jour=date_jour,
        mois=mois,
        annee=annee,
        date_debut=date_debut,
        date_fin=date_fin,
        service_filtre=service or None,
        employe_filtre=employe or None
    )

    pdf_buffer = generer_pdf_rapport(
        titre_periode=donnees["titre_periode"],
        nom_service=donnees["nom_service"],
        nom_employe=donnees["nom_employe"],
        stats_globales=donnees["stats_globales"],
        synthese_employes=donnees["synthese_employes"],
        lignes_presences=donnees["lignes_detail"]
    )

    nom_fichier = f"Rapport_{type_periode}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
    return send_file(
        pdf_buffer,
        mimetype="application/pdf",
        as_attachment=True,
        download_name=nom_fichier
    )


def get_pointages(date_debut=None, date_fin=None, employe_filtre=None):
    conn = sqlite3.connect("gestion_absences.db")
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    requete = """
        SELECT pointages.id,
               pointages.employe_id,
               employes.nom,
               employes.service,
               pointages.date_heure,
               pointages.type
        FROM pointages
        JOIN employes ON pointages.employe_id = employes.id
        WHERE 1=1
    """
    params = []

    if date_debut:
        requete += " AND date(pointages.date_heure) >= ?"
        params.append(date_debut)

    if date_fin:
        requete += " AND date(pointages.date_heure) <= ?"
        params.append(date_fin)

    if employe_filtre:
        requete += " AND employes.id = ?"
        params.append(employe_filtre)

    requete += " ORDER BY pointages.date_heure DESC"

    cur.execute(requete, params)
    resultats = cur.fetchall()
    conn.close()
    return resultats


@app.route("/pointages")
@login_required
def route_pointages():
    if not current_user.is_admin:
        return redirect(url_for("espace_employe"))
    date_debut = request.args.get("date_debut", "").strip()
    date_fin   = request.args.get("date_fin", "").strip()
    employe_filtre = request.args.get("employe", "").strip()

    pointages = get_pointages(date_debut or None, date_fin or None, employe_filtre or None)
    employes  = get_tous_employes()

    employe_selectionne = None
    if employe_filtre:
        for e in employes:
            if str(e["id"]) == str(employe_filtre):
                employe_selectionne = e
                break

    return render_template(
        "pointages.html",
        pointages=pointages,
        employes=employes,
        date_debut=date_debut,
        date_fin=date_fin,
        employe_filtre=employe_filtre,
        employe_selectionne=employe_selectionne,
        aujourd_hui=date.today().isoformat(),
        etat_sync=etat_synchronisation
    )


if __name__ == "__main__":
    # N'exécuter les initialisations QU'UNE SEULE FOIS dans le processus principal.
    # En mode debug, Werkzeug lance 2 processus (main + reloader) : sans ce guard,
    # les deux tentent d'écrire en même temps → sqlite3.OperationalError: database is locked
    if os.environ.get("WERKZEUG_RUN_MAIN") != "true":
        initialiser_tables_auth()
        initialiser_table_horaires()
        generer_presences()

    # La sync auto démarre uniquement dans le processus reloader (ou hors debug)
    if os.environ.get("WERKZEUG_RUN_MAIN") == "true" or not app.debug:
        demarrer_synchronisation_auto()

    app.run(debug=True)