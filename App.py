import streamlit as st
import sqlite3
import pandas as pd
from datetime import datetime, timedelta
import urllib.parse

# --- DATABASE SETUP ---
DB_FILE = "yango_fleet_pro.db"

def init_db():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    
    # 1. Vehicles Table (Includes Road Tax, Fitness, Insurance, and Odometer)
    c.execute('''
        CREATE TABLE IF NOT EXISTS vehicles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            plate_number TEXT UNIQUE,
            driver_name TEXT,
            driver_phone TEXT,
            weekly_target REAL,
            running_balance REAL DEFAULT 0.0,
            current_odometer INTEGER,
            last_service_date DATE,
            last_service_mileage INTEGER,
            next_service_mileage INTEGER,
            road_tax_expiry DATE,
            fitness_expiry DATE,
            insurance_expiry DATE
        )
    ''')
    
    # 2. Payments Table
    c.execute('''
        CREATE TABLE IF NOT EXISTS payments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            plate_number TEXT,
            week_start_date DATE,
            amount_paid REAL,
            target_amount REAL,
            balance_after_payment REAL,
            status TEXT,
            payment_date DATE,
            FOREIGN KEY (plate_number) REFERENCES vehicles (plate_number)
        )
    ''')
    
    conn.commit()
    conn.close()

init_db()

def get_db_connection():
    return sqlite3.connect(DB_FILE)

# --- HELPER: WHATSAPP LINK GENERATOR ---
def make_whatsapp_link(phone_number, message):
    # Format phone number for international format (assuming Zambia +260 if omitted)
    phone = phone_number.strip().replace("+", "").replace(" ", "")
    if phone.startswith("0"):
        phone = "260" + phone[1:]
    encoded_message = urllib.parse.quote(message)
    return f"https://wa.me/{phone}?text={encoded_message}"

# Page Config
st.set_page_config(page_title="Yango Fleet Manager Pro", page_icon="🚗", layout="wide")
st.title("🚗 Yango Fleet Management System")

# Navigation Tabs
tab_dash, tab_payments, tab_service, tab_compliance, tab_fleet = st.tabs([
    "🚨 Dashboard & WhatsApp", 
    "💵 Payment Ledger", 
    "🔧 Odometer & Service", 
    "📋 Compliance (Tax/Fitness/Ins)",
    "🚘 Fleet & Drivers"
])

# ==========================================
# TAB 1: DASHBOARD & WHATSAPP REMINDERS
# ==========================================
with tab_dash:
    st.header("Executive Summary & Alerts")
    
    conn = get_db_connection()
    vehicles_df = pd.read_sql("SELECT * FROM vehicles", conn)
    conn.close()
    
    if vehicles_df.empty:
        st.info("No vehicles registered yet. Go to the 'Fleet & Drivers' tab to add your 10 cars.")
    else:
        today = datetime.today().date()
        seven_days = today + timedelta(days=7)
        
        # Calculate Quick Metrics
        total_cars = len(vehicles_df)
        total_debt = vehicles_df[vehicles_df['running_balance'] > 0]['running_balance'].sum()
        service_due_count = len(vehicles_df[vehicles_df['current_odometer'] >= vehicles_df['next_service_mileage']])
        
        col1, col2, col3 = st.columns(3)
        col1.metric("Active Fleet", total_cars)
        col2.metric("Total Driver Debt (ZMW)", f"K{total_debt:,.2f}")
        col3.metric("Cars Needing Service", service_due_count)
        
        st.divider()
        
        st.subheader("⚠️ Urgent Driver Action Items")
        
        for _, row in vehicles_df.iterrows():
            alerts = []
            
            # Debt Alert
            if row['running_balance'] > 0:
                alerts.append(f"Outstanding Debt: K{row['running_balance']:,.2f}")
            
            # Compliance Alerts
            for doc, col_name in [("Road Tax", "road_tax_expiry"), ("Fitness", "fitness_expiry"), ("Insurance", "insurance_expiry")]:
                if row[col_name]:
                    exp_date = datetime.strptime(str(row[col_name]), '%Y-%m-%d').date()
                    if exp_date <= seven_days:
                        days_left = (exp_date - today).days
                        status_str = f"EXPIRED" if days_left < 0 else f"expires in {days_left} days"
                        alerts.append(f"{doc} {status_str} ({exp_date})")
            
            # Service Alert
            km_remaining = row['next_service_mileage'] - row['current_odometer']
            if km_remaining <= 500:
                alerts.append(f"Service Due in {km_remaining} km (Odo: {row['current_odometer']} km)")
                
            if alerts:
                with st.expander(f"⚠️ **{row['plate_number']}** - {row['driver_name']} ({len(alerts)} alerts)", expanded=True):
                    for a in alerts:
                        st.write(f"- {a}")
                    
                    # Formulate WhatsApp Message
                    msg = f"Hello {row['driver_name']}, this is a reminder regarding your Yango car ({row['plate_number']}):\n"
                    for a in alerts:
                        msg += f"• {a}\n"
                    msg += "\nPlease settle your balance or coordinate with me as soon as possible. Thank you!"
                    
                    wa_url = make_whatsapp_link(row['driver_phone'], msg)
                    st.markdown(f"[📲 **Send WhatsApp Reminder to {row['driver_name']}**]({wa_url})", unsafe_allow_html=True)

# ==========================================
# TAB 2: PAYMENTS & RUNNING BALANCE LEDGER
# ==========================================
with tab_payments:
    st.header("Weekly Payment Ledger")
    
    conn = get_db_connection()
    vehicles_df = pd.read_sql("SELECT plate_number, driver_name, weekly_target, running_balance FROM vehicles", conn)
    
    today = datetime.today().date()
    current_week = today - timedelta(days=today.weekday())
    
    col_left, col_right = st.columns([1, 2])
    
    with col_left:
        st.subheader("Record Payment")
        if not vehicles_df.empty:
            with st.form("record_payment"):
                car_choice = st.selectbox(
                    "Select Driver", 
                    vehicles_df['plate_number'] + " - " + vehicles_df['driver_name']
                )
                plate = car_choice.split(" - ")[0]
                car_info = vehicles_df[vehicles_df['plate_number'] == plate].iloc[0]
                
                st.info(f"Target: K{car_info['weekly_target']:,.2f} | Current Debt: K{car_info['running_balance']:,.2f}")
                
                week_date = st.date_input("Week Starting Date", current_week)
                amount_paid = st.number_input("Amount Paid Today (ZMW)", min_value=0.0, value=float(car_info['weekly_target']), step=50.0)
                
                submit_pay = st.form_submit_button("Submit Payment")
                
                if submit_pay:
                    c = conn.cursor()
                    
                    # Calculate new balance
                    # New Debt = Previous Debt + (Target - Paid)
                    shortfall = car_info['weekly_target'] - amount_paid
                    new_balance = car_info['running_balance'] + shortfall
                    
                    status = "Full Payment" if shortfall <= 0 else "Partial Payment" if amount_paid > 0 else "Unpaid"
                    
                    # Log Payment
                    c.execute('''
                        INSERT INTO payments (plate_number, week_start_date, amount_paid, target_amount, balance_after_payment, status, payment_date)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                    ''', (plate, str(week_date), amount_paid, car_info['weekly_target'], new_balance, status, str(today)))
                    
                    # Update Vehicle Running Balance
                    c.execute("UPDATE vehicles SET running_balance = ? WHERE plate_number = ?", (new_balance, plate))
                    
                    conn.commit()
                    st.success(f"Recorded K{amount_paid:,.2f} for {plate}. Updated Debt Balance: K{new_balance:,.2f}")
                    st.rerun()
        else:
            st.warning("No vehicles registered.")
            
    with col_right:
        st.subheader("Payment History Log")
        payments_df = pd.read_sql("SELECT * FROM payments ORDER BY id DESC", conn)
        st.dataframe(payments_df, use_container_width=True)
        
    conn.close()

# ==========================================
# TAB 3: ODOMETER & SERVICE TRACKING
# ==========================================
with tab_service:
    st.header("Odometer & Service Management")
    
    conn = get_db_connection()
    vehicles_df = pd.read_sql("SELECT plate_number, driver_name, current_odometer, last_service_date, next_service_mileage FROM vehicles", conn)
    
    col1, col2 = st.columns(2)
    
    with col1:
        st.subheader("Update Current Odometer")
        if not vehicles_df.empty:
            with st.form("update_odo"):
                car_choice = st.selectbox("Vehicle", vehicles_df['plate_number'] + " - " + vehicles_df['driver_name'], key="odo_car")
                plate = car_choice.split(" - ")[0]
                current_odo = vehicles_df[vehicles_df['plate_number'] == plate]['current_odometer'].values[0]
                
                new_odo = st.number_input("New Odometer Reading (km)", min_value=int(current_odo), value=int(current_odo), step=100)
                
                if st.form_submit_button("Update Mileage"):
                    c = conn.cursor()
                    c.execute("UPDATE vehicles SET current_odometer = ? WHERE plate_number = ?", (new_odo, plate))
                    conn.commit()
                    st.success(f"Updated {plate} mileage to {new_odo:,} km!")
                    st.rerun()

    with col2:
        st.subheader("Log Completed Service")
        if not vehicles_df.empty:
            with st.form("log_service"):
                car_choice = st.selectbox("Vehicle", vehicles_df['plate_number'] + " - " + vehicles_df['driver_name'], key="serv_car")
                plate = car_choice.split(" - ")[0]
                
                serv_date = st.date_input("Service Date", datetime.today().date())
                serv_mileage = st.number_input("Service Performed At (km)", min_value=0, step=500)
                interval = st.number_input("Next Service Interval (km)", value=5000, step=500)
                
                if st.form_submit_button("Record Service"):
                    c = conn.cursor()
                    next_m = serv_mileage + interval
                    c.execute('''
                        UPDATE vehicles 
                        SET last_service_date = ?, last_service_mileage = ?, next_service_mileage = ?, current_odometer = MAX(current_odometer, ?)
                        WHERE plate_number = ?
                    ''', (str(serv_date), serv_mileage, next_m, serv_mileage, plate))
                    conn.commit()
                    st.success(f"Service logged! Next service set at {next_m:,} km.")
                    st.rerun()

    st.subheader("Service Schedule Overview")
    serv_overview = pd.read_sql('''
        SELECT plate_number, driver_name, current_odometer, last_service_date, last_service_mileage, next_service_mileage,
        (next_service_mileage - current_odometer) AS km_until_next_service
        FROM vehicles
    ''', conn)
    st.dataframe(serv_overview, use_container_width=True)
    conn.close()

# ==========================================
# TAB 4: COMPLIANCE TRACKING
# ==========================================
with tab_compliance:
    st.header("Document Compliance (Road Tax, Fitness, Insurance)")
    
    conn = get_db_connection()
    vehicles_df = pd.read_sql("SELECT plate_number, driver_name, road_tax_expiry, fitness_expiry, insurance_expiry FROM vehicles", conn)
    
    with st.expander("🔄 Renew / Update Compliance Dates"):
        if not vehicles_df.empty:
            with st.form("update_docs"):
                car_choice = st.selectbox("Select Vehicle", vehicles_df['plate_number'] + " - " + vehicles_df['driver_name'], key="doc_car")
                plate = car_choice.split(" - ")[0]
                
                col_a, col_b, col_c = st.columns(3)
                new_tax = col_a.date_input("New Road Tax Expiry")
                new_fit = col_b.date_input("New Fitness Expiry")
                new_ins = col_c.date_input("New Insurance Expiry")
                
                if st.form_submit_button("Update Documents"):
                    c = conn.cursor()
                    c.execute('''
                        UPDATE vehicles 
                        SET road_tax_expiry = ?, fitness_expiry = ?, insurance_expiry = ?
                        WHERE plate_number = ?
                    ''', (str(new_tax), str(new_fit), str(new_ins), plate))
                    conn.commit()
                    st.success(f"Compliance dates updated for {plate}!")
                    st.rerun()

    st.subheader("Compliance Master Sheet")
    st.dataframe(vehicles_df, use_container_width=True)
    conn.close()

# ==========================================
# TAB 5: FLEET & DRIVER REGISTRATION
# ==========================================
with tab_fleet:
    st.header("Fleet & Driver Management")
    
    with st.expander("➕ Register New Vehicle & Driver", expanded=True):
        with st.form("add_vehicle"):
            c1, c2, c3 = st.columns(3)
            plate = c1.text_input("Plate Number (e.g., BAL 1234)")
            driver = c2.text_input("Driver Name")
            phone = c3.text_input("Driver Phone (e.g., 0977123456)")
            
            c4, c5, c6 = st.columns(3)
            target = c4.number_input("Weekly Target (ZMW)", value=1500.0, step=100.0)
            initial_balance = c5.number_input("Initial Debt Balance (ZMW)", value=0.0, step=100.0)
            current_odo = c6.number_input("Current Odometer (km)", value=100000, step=1000)
            
            st.subheader("Document Expiry Dates")
            c7, c8, c9 = st.columns(3)
            road_tax_exp = c7.date_input("Road Tax Expiry")
            fitness_exp = c8.date_input("Fitness Expiry")
            ins_exp = c9.date_input("Insurance Expiry")
            
            c10, c11 = st.columns(2)
            last_serv_date = c10.date_input("Last Service Date")
            last_serv_km = c11.number_input("Last Service Mileage (km)", value=100000)
            
            if st.form_submit_button("Register Vehicle"):
                conn = get_db_connection()
                c = conn.cursor()
                try:
                    next_serv_km = last_serv_km + 5000
                    c.execute('''
                        INSERT INTO vehicles 
                        (plate_number, driver_name, driver_phone, weekly_target, running_balance, current_odometer, 
                         last_service_date, last_service_mileage, next_service_mileage, road_tax_expiry, fitness_expiry, insurance_expiry)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ''', (plate, driver, phone, target, initial_balance, current_odo, 
                          str(last_serv_date), last_serv_km, next_serv_km, 
                          str(road_tax_exp), str(fitness_exp), str(ins_exp)))
                    conn.commit()
                    st.success(f"Vehicle {plate} and driver {driver} successfully registered!")
                    st.rerun()
                except sqlite3.IntegrityError:
                    st.error("A vehicle with this plate number already exists.")
                conn.close()

    st.subheader("Current Registered Fleet")
    conn = get_db_connection()
    all_vehicles = pd.read_sql("SELECT * FROM vehicles", conn)
    st.dataframe(all_vehicles, use_container_width=True)
    conn.close()
