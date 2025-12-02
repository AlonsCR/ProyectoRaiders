from flask import Flask, render_template, request, redirect, url_for, session, flash
import psycopg2
import psycopg2.extras

app = Flask(__name__)
app.secret_key = 'raiders_secret_key'

def get_db_connection():
    if 'db_user' not in session:
        return None
    try:
        conn = psycopg2.connect(
            host="localhost",
            database="raiders",
            user=session['db_user'],
            password=session['db_pass']
        )
        return conn
    except Exception as e:
        print(f"Error de conexión: {e}")
        return None

@app.route('/', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        usuario = request.form['usuario']
        password = request.form['password']

        try:
            conn_test = psycopg2.connect(
                host="localhost",
                database="raiders",
                user=usuario,
                password=password
            )
            conn_test.close()
            session['db_user'] = usuario
            session['db_pass'] = password
            return redirect(url_for('dashboard'))
        except Exception as e:
            flash('Error: Usuario o contraseña incorrectos.')
            return render_template('login.html')
    return render_template('login.html')

@app.route('/dashboard')
def dashboard():
    if 'db_user' not in session: return redirect(url_for('login'))
    conn = get_db_connection()
    if not conn: return redirect(url_for('login'))
    cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
    rol = session['db_user']
    datos = {}
    modo = request.args.get('modo', 'coach')

    try:
        if modo == 'stats':
            query_stats = """
                SELECT 
                    j.nombre, 
                    j.posicion, 
                    COALESCE(SUM(e.touchdowns), 0) as touchdowns, 
                    COALESCE(SUM(e.yardas_totales), 0) as yardas, 
                    COALESCE(SUM(e.tackleos), 0) as tackles, 
                    COALESCE(SUM(e.capturas), 0) as sacks,
                    fn_calcular_rendimiento(
                        COALESCE(SUM(e.yardas_totales), 0)::INT,
                        COALESCE(SUM(e.touchdowns), 0)::INT,
                        COALESCE(SUM(e.capturas), 0)
                    ) as rendimiento
                FROM jugadores j
                LEFT JOIN estadisticas e ON j.id = e.id_jugador
                GROUP BY j.id, j.nombre, j.posicion
                ORDER BY rendimiento DESC
            """
            cur.execute(query_stats)
            datos['stats'] = cur.fetchall()
        elif rol == 'gerente_general' and modo == 'auditoria':
            cur.execute("""
                SELECT 
                    a.fecha_cambio,
                    j.nombre,
                    a.salario_anterior,
                    a.salario_nuevo,
                    (a.salario_nuevo - a.salario_anterior) as diferencia,
                    a.usuario_responsable
                FROM auditoria_salarios a
                JOIN jugadores j ON a.id_jugador = j.id
                ORDER BY a.fecha_cambio DESC
            """)
            datos['auditoria'] = cur.fetchall()
        elif rol == 'gerente_general':
            cur.execute("SELECT * FROM jugadores ORDER BY numero")
            datos['roster'] = cur.fetchall()
        elif rol == 'head_coach':
            cur.execute("SELECT * FROM v_coach_roster ORDER BY numero")
            datos['roster'] = cur.fetchall()
        elif rol == 'prensa_raiders':
            if modo == 'vistas':
                cur.execute("SELECT * FROM v_origen_jugadores ORDER BY nombre")
                datos['origen'] = cur.fetchall()
                cur.execute("SELECT * FROM v_datos_vitales ORDER BY numero")
                datos['vitales'] = cur.fetchall()
            else:
                cur.execute("SELECT * FROM v_coach_roster ORDER BY numero")
                datos['roster'] = cur.fetchall()
    except Exception as e:
        flash(f"Error cargando datos: {e}")
        print(f"DEBUG ERROR SQL: {e}")
    finally:
        cur.close()
        conn.close()
    return render_template('dashboard.html', rol=rol, datos=datos, modo=modo)

@app.route('/agregar', methods=['POST'])
def agregar_jugador():
    if 'db_user' not in session: return redirect(url_for('login'))
    nombre = request.form['nombre']
    try:
        numero = int(request.form['numero'])
    except ValueError:
        flash("Error: El número debe ser un valor numérico.")
        return redirect(url_for('dashboard'))
    posicion = request.form['posicion']
    altura = request.form['altura']
    peso = request.form['peso']
    uni = request.form['universidad']
    salario = request.form['salario']
    if numero < 0:
        flash("El número de camiseta no puede ser negativo.")
        return redirect(url_for('dashboard'))
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("""
            INSERT INTO jugadores 
            (nombre, numero, posicion, altura_cm, peso_kg, universidad, salario, estado, en_plantilla)
            VALUES (%s, %s, %s, %s, %s, %s, %s, 'ACTIVO', TRUE)
        """, (nombre, numero, posicion, altura, peso, uni, salario))
        conn.commit()
        flash(f"Jugador {nombre} (#{numero}) firmado correctamente.")
    except psycopg2.errors.InsufficientPrivilege:
        conn.rollback()
        flash("ERROR DE SEGURIDAD: Tu rol no tiene permiso para contratar jugadores.")
    except Exception as e:
        conn.rollback()
        flash(f"Error al insertar: {e}")
    finally:
        cur.close()
        conn.close()
    return redirect(url_for('dashboard'))

@app.route('/cortar', methods=['POST'])
def cortar_jugador():
    if 'db_user' not in session: return redirect(url_for('login'))
    if session['db_user'] != 'gerente_general':
        flash("ACCESO DENEGADO: Solo el Gerente puede cortar jugadores.")
        return redirect(url_for('dashboard'))

    id_jugador = request.form['id']
    conn = get_db_connection()
    cur = conn.cursor()

    try:
        cur.execute("""
                    UPDATE jugadores 
                    SET en_plantilla = FALSE, estado = 'CORTADO' 
                    WHERE id = %s
                """, (id_jugador,))
        conn.commit()
        flash("Jugador cortado")
    except Exception as e:
        conn.rollback()
        flash(f"Error al cortar jugador: {e}")
    finally:
        cur.close()
        conn.close()
    return redirect(url_for('dashboard'))

@app.route('/actualizar', methods=['POST'])
@app.route('/actualizar', methods=['POST'])
def actualizar_jugador():
    if 'db_user' not in session: return redirect(url_for('login'))

    id_jugador = request.form['id']
    nuevo_peso = request.form['peso']
    nuevo_estado = request.form['estado']

    nuevo_salario = request.form.get('salario')

    conn = get_db_connection()
    cur = conn.cursor()

    try:
        if session['db_user'] == 'gerente_general' and nuevo_salario:
            cur.execute("""
                UPDATE jugadores 
                SET peso_kg = %s, estado = %s, salario = %s
                WHERE id = %s
            """, (nuevo_peso, nuevo_estado, nuevo_salario, id_jugador))
        else:
            cur.execute("""
                UPDATE jugadores 
                SET peso_kg = %s, estado = %s 
                WHERE id = %s
            """, (nuevo_peso, nuevo_estado, id_jugador))

        conn.commit()
        flash("Datos actualizados correctamente.")
    except Exception as e:
        conn.rollback()
        flash(f"Error al actualizar: {e}")
    finally:
        cur.close()
        conn.close()

    return redirect(url_for('dashboard'))

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

def llenar_db():
    import random
    import psycopg2

    nombres = ["James", "John", "Robert", "Michael", "William", "David", "Richard", "Joseph", "Thomas", "Charles", "Daniel", "Matthew", "Anthony", "Donald",
               "Mark", "Paul", "Steven", "Andrew", "Kenneth", "Joshua", "Kevin", "Brian", "George", "Edward", "Ronald", "Timothy", "Jason", "Jeffrey", "Ryan",
               "Jacob", "Gary", "Nicholas", "Eric", "Jonathan", "Stephen", "Larry", "Justin", "Scott", "Brandon", "Benjamin", "Samuel", "Frank", "Gregory",
               "Raymond", "Alexander", "Patrick", "Jack", "Dennis", "Jerry", "Carlos", "Luis", "Jose", "Antonio", "Manuel"]
    apellidos = ["Smith", "Johnson", "Williams", "Brown", "Jones", "Garcia", "Miller", "Davis", "Rodriguez", "Martinez", "Hernandez", "Lopez", "Gonzalez",
                 "Wilson", "Anderson", "Thomas", "Taylor", "Moore", "Jackson", "Martin", "Lee", "Perez", "Thompson", "White", "Harris", "Sanchez", "Clark",
                 "Ramirez", "Lewis", "Robinson", "Walker", "Young", "Allen", "King", "Wright", "Scott", "Torres", "Nguyen", "Hill", "Flores", "Green", "Adams",
                 "Nelson", "Baker", "Hall", "Rivera", "Campbell", "Mitchell", "Carter", "Roberts"]
    universidades = ["Alabama", "Ohio State", "Georgia", "Clemson", "Notre Dame", "LSU", "Michigan", "Oklahoma", "Florida", "Texas", "USC", "Penn State",
                     "Oregon", "Auburn", "Tennessee", "Wisconsin", "Miami", "FSU", "Texas A&M", "Washington", "UCLA", "Stanford", "Ole Miss", "Utah"]
    posiciones = ['QB', 'WR', 'RB', 'DE', 'LB', 'CB', 'OT', 'DT', 'TE', 'K']
    rivales = ['Chiefs', 'Broncos', 'Chargers', 'Patriots', 'Steelers', 'Cowboys', '49ers', 'Ravens', 'Bills', 'Eagles']

    try:
        conn = psycopg2.connect(
            host="localhost",
            database="raiders",
            user="gerente_general",
            password="1975"
        )
    except Exception as e:
        print(f"Error de conexión: {e}")
        return

    cur = conn.cursor()

    try:
        jugadores_data = []
        estadisticas_data = []

        for _ in range(1000):
            nombre = f"{random.choice(nombres)} {random.choice(apellidos)}"
            numero = random.randint(0, 99)
            pos = random.choice(posiciones)
            uni = random.choice(universidades)
            salario = round(random.uniform(750000, 25000000), 2)
            if pos in ['OT', 'DT', 'DE']:
                peso = round(random.uniform(120, 160), 2)
                altura = round(random.uniform(190, 205), 2)
            elif pos in ['WR', 'CB', 'RB', 'K']:
                peso = round(random.uniform(80, 100), 2)
                altura = round(random.uniform(175, 190), 2)
            else:
                peso = round(random.uniform(90, 115), 2)
                altura = round(random.uniform(180, 198), 2)

            peso = float(f"{peso:.2f}")
            altura = float(f"{altura:.2f}")
            salario = float(f"{salario:.2f}")
            jugadores_data.append((nombre, numero, pos, altura, peso, uni, salario))

        args = ",".join(
            cur.mogrify("(%s,%s,%s,%s,%s,%s,%s,'ACTIVO',TRUE)", x).decode("utf-8")
            for x in jugadores_data
        )

        cur.execute(
            "INSERT INTO jugadores (nombre, numero, posicion, altura_cm, peso_kg, universidad, salario, estado, en_plantilla) "
            "VALUES " + args + " RETURNING id"
        )

        ids_generados = cur.fetchall()

        for fila in ids_generados:
            nuevo_id = fila[0]
            estadisticas_data.append((
                nuevo_id,
                random.randint(1, 18),
                random.choice(rivales),
                random.randint(0, 150),
                random.randint(0, 3),
                random.randint(0, 12),
                round(random.uniform(0, 3), 1)
            ))

        args_stats = ",".join(
            cur.mogrify("(%s,%s,%s,%s,%s,%s,%s)", x).decode("utf-8")
            for x in estadisticas_data
        )

        cur.execute(
            "INSERT INTO estadisticas (id_jugador, semana, rival, yardas_totales, touchdowns, tackleos, capturas) "
            "VALUES " + args_stats
        )

        conn.commit()
        print("Base de datos llenada exitosamente")

    except Exception as e:
        conn.rollback()
        print(f"Error durante la inserción: {e}")

    finally:
        cur.close()
        conn.close()
if __name__ == '__main__':
    app.run(debug=True, port=5001)
    #llenar_db()