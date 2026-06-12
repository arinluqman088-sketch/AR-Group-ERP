from __future__ import annotations

import os
import sqlite3
from datetime import datetime, date
from functools import wraps
from typing import Any

from flask import Flask, render_template, request, redirect, url_for, flash, session

APP_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(APP_DIR, "ar_group_erp.db")

app = Flask(__name__)
app.secret_key = os.environ.get("AR_GROUP_SECRET", "change-this-secret-key")


def get_db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db() -> None:
    conn = get_db()
    cur = conn.cursor()
    cur.executescript(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            email TEXT NOT NULL UNIQUE,
            password TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT 'admin',
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sku TEXT UNIQUE,
            name TEXT NOT NULL,
            category TEXT,
            cost_price REAL NOT NULL DEFAULT 0,
            sell_price REAL NOT NULL DEFAULT 0,
            stock INTEGER NOT NULL DEFAULT 0,
            min_stock INTEGER NOT NULL DEFAULT 3,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS customers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            phone TEXT,
            address TEXT,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS suppliers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            phone TEXT,
            address TEXT,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS sales (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            invoice_no TEXT NOT NULL UNIQUE,
            customer_id INTEGER,
            subtotal REAL NOT NULL DEFAULT 0,
            discount REAL NOT NULL DEFAULT 0,
            total REAL NOT NULL DEFAULT 0,
            note TEXT,
            created_at TEXT NOT NULL,
            FOREIGN KEY(customer_id) REFERENCES customers(id)
        );

        CREATE TABLE IF NOT EXISTS sale_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sale_id INTEGER NOT NULL,
            product_id INTEGER NOT NULL,
            quantity INTEGER NOT NULL,
            unit_price REAL NOT NULL,
            total REAL NOT NULL,
            FOREIGN KEY(sale_id) REFERENCES sales(id) ON DELETE CASCADE,
            FOREIGN KEY(product_id) REFERENCES products(id)
        );

        CREATE TABLE IF NOT EXISTS purchases (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            supplier_id INTEGER,
            product_id INTEGER NOT NULL,
            quantity INTEGER NOT NULL,
            unit_cost REAL NOT NULL,
            total REAL NOT NULL,
            note TEXT,
            created_at TEXT NOT NULL,
            FOREIGN KEY(supplier_id) REFERENCES suppliers(id),
            FOREIGN KEY(product_id) REFERENCES products(id)
        );

        CREATE TABLE IF NOT EXISTS expenses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            amount REAL NOT NULL,
            category TEXT,
            note TEXT,
            created_at TEXT NOT NULL
        );
        """
    )

    user = cur.execute("SELECT id FROM users WHERE email = ?", ("admin@argroup.com",)).fetchone()
    if not user:
        cur.execute(
            "INSERT INTO users (name, email, password, role, created_at) VALUES (?, ?, ?, ?, ?)",
            ("AR Group Admin", "admin@argroup.com", "admin123", "admin", now()),
        )

    count_products = cur.execute("SELECT COUNT(*) AS c FROM products").fetchone()["c"]
    if count_products == 0:
        demo_products = [
            ("P-001", "قاوەی عەرەبی", "Drinks", 2500, 5000, 30, 5),
            ("P-002", "چای", "Drinks", 500, 1000, 80, 10),
            ("P-003", "کێک", "Food", 1500, 3000, 20, 5),
        ]
        cur.executemany(
            "INSERT INTO products (sku, name, category, cost_price, sell_price, stock, min_stock, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            [(*p, now()) for p in demo_products],
        )

    conn.commit()
    conn.close()


def now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def today_str() -> str:
    return date.today().strftime("%Y-%m-%d")


def money(value: Any) -> str:
    try:
        return f"{float(value):,.0f} IQD"
    except (TypeError, ValueError):
        return "0 IQD"


app.jinja_env.filters["money"] = money


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("user_id"):
            return redirect(url_for("login"))
        return view(*args, **kwargs)

    return wrapped


@app.before_request
def setup() -> None:
    if not os.path.exists(DB_PATH):
        init_db()


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email", "").strip()
        password = request.form.get("password", "").strip()
        conn = get_db()
        user = conn.execute("SELECT * FROM users WHERE email = ? AND password = ?", (email, password)).fetchone()
        conn.close()
        if user:
            session["user_id"] = user["id"]
            session["user_name"] = user["name"]
            return redirect(url_for("dashboard"))
        flash("ئیمەیل یان پاسۆرد هەڵەیە", "danger")
    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/")
@login_required
def dashboard():
    conn = get_db()
    today = today_str()
    stats = {
        "products": conn.execute("SELECT COUNT(*) c FROM products").fetchone()["c"],
        "customers": conn.execute("SELECT COUNT(*) c FROM customers").fetchone()["c"],
        "suppliers": conn.execute("SELECT COUNT(*) c FROM suppliers").fetchone()["c"],
        "sales_today": conn.execute("SELECT COALESCE(SUM(total), 0) total FROM sales WHERE date(created_at) = ?", (today,)).fetchone()["total"],
        "expenses_today": conn.execute("SELECT COALESCE(SUM(amount), 0) total FROM expenses WHERE date(created_at) = ?", (today,)).fetchone()["total"],
        "stock_value": conn.execute("SELECT COALESCE(SUM(stock * cost_price), 0) total FROM products").fetchone()["total"],
        "low_stock": conn.execute("SELECT COUNT(*) c FROM products WHERE stock <= min_stock").fetchone()["c"],
    }
    recent_sales = conn.execute(
        """
        SELECT s.*, c.name AS customer_name
        FROM sales s
        LEFT JOIN customers c ON c.id = s.customer_id
        ORDER BY s.id DESC LIMIT 8
        """
    ).fetchall()
    low_stock_products = conn.execute("SELECT * FROM products WHERE stock <= min_stock ORDER BY stock ASC LIMIT 8").fetchall()
    conn.close()
    return render_template("dashboard.html", stats=stats, recent_sales=recent_sales, low_stock_products=low_stock_products)


@app.route("/products", methods=["GET", "POST"])
@login_required
def products():
    conn = get_db()
    if request.method == "POST":
        try:
            conn.execute(
                """
                INSERT INTO products (sku, name, category, cost_price, sell_price, stock, min_stock, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    request.form.get("sku", "").strip() or None,
                    request.form.get("name", "").strip(),
                    request.form.get("category", "").strip(),
                    float(request.form.get("cost_price") or 0),
                    float(request.form.get("sell_price") or 0),
                    int(request.form.get("stock") or 0),
                    int(request.form.get("min_stock") or 3),
                    now(),
                ),
            )
            conn.commit()
            flash("کاڵا زیاد کرا", "success")
        except sqlite3.IntegrityError:
            flash("SKU پێشتر بەکارهاتووە", "danger")
        return redirect(url_for("products"))
    items = conn.execute("SELECT * FROM products ORDER BY id DESC").fetchall()
    conn.close()
    return render_template("products.html", products=items)


@app.route("/customers", methods=["GET", "POST"])
@login_required
def customers():
    conn = get_db()
    if request.method == "POST":
        conn.execute(
            "INSERT INTO customers (name, phone, address, created_at) VALUES (?, ?, ?, ?)",
            (request.form.get("name"), request.form.get("phone"), request.form.get("address"), now()),
        )
        conn.commit()
        flash("کڕیار زیاد کرا", "success")
        return redirect(url_for("customers"))
    rows = conn.execute("SELECT * FROM customers ORDER BY id DESC").fetchall()
    conn.close()
    return render_template("customers.html", customers=rows)


@app.route("/suppliers", methods=["GET", "POST"])
@login_required
def suppliers():
    conn = get_db()
    if request.method == "POST":
        conn.execute(
            "INSERT INTO suppliers (name, phone, address, created_at) VALUES (?, ?, ?, ?)",
            (request.form.get("name"), request.form.get("phone"), request.form.get("address"), now()),
        )
        conn.commit()
        flash("دابینکەر زیاد کرا", "success")
        return redirect(url_for("suppliers"))
    rows = conn.execute("SELECT * FROM suppliers ORDER BY id DESC").fetchall()
    conn.close()
    return render_template("suppliers.html", suppliers=rows)


@app.route("/sales", methods=["GET", "POST"])
@login_required
def sales():
    conn = get_db()
    if request.method == "POST":
        product_id = int(request.form.get("product_id") or 0)
        customer_id = request.form.get("customer_id") or None
        quantity = int(request.form.get("quantity") or 1)
        discount = float(request.form.get("discount") or 0)
        note = request.form.get("note") or ""
        product = conn.execute("SELECT * FROM products WHERE id = ?", (product_id,)).fetchone()
        if not product:
            flash("کاڵا نەدۆزرایەوە", "danger")
        elif quantity <= 0:
            flash("ژمارە دەبێت زیاتر لە 0 بێت", "danger")
        elif product["stock"] < quantity:
            flash("ستۆک بەشی ئەم فرۆشتنە ناکات", "danger")
        else:
            unit_price = float(request.form.get("unit_price") or product["sell_price"])
            subtotal = unit_price * quantity
            total = max(subtotal - discount, 0)
            invoice_no = f"INV-{datetime.now().strftime('%Y%m%d%H%M%S')}"
            cur = conn.cursor()
            cur.execute(
                "INSERT INTO sales (invoice_no, customer_id, subtotal, discount, total, note, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (invoice_no, customer_id, subtotal, discount, total, note, now()),
            )
            sale_id = cur.lastrowid
            cur.execute(
                "INSERT INTO sale_items (sale_id, product_id, quantity, unit_price, total) VALUES (?, ?, ?, ?, ?)",
                (sale_id, product_id, quantity, unit_price, total),
            )
            cur.execute("UPDATE products SET stock = stock - ? WHERE id = ?", (quantity, product_id))
            conn.commit()
            flash(f"وەسل دروست کرا: {invoice_no}", "success")
        return redirect(url_for("sales"))

    product_rows = conn.execute("SELECT * FROM products ORDER BY name ASC").fetchall()
    customer_rows = conn.execute("SELECT * FROM customers ORDER BY name ASC").fetchall()
    sale_rows = conn.execute(
        """
        SELECT s.*, c.name AS customer_name, p.name AS product_name, si.quantity
        FROM sales s
        LEFT JOIN customers c ON c.id = s.customer_id
        LEFT JOIN sale_items si ON si.sale_id = s.id
        LEFT JOIN products p ON p.id = si.product_id
        ORDER BY s.id DESC LIMIT 50
        """
    ).fetchall()
    conn.close()
    return render_template("sales.html", products=product_rows, customers=customer_rows, sales=sale_rows)


@app.route("/purchases", methods=["GET", "POST"])
@login_required
def purchases():
    conn = get_db()
    if request.method == "POST":
        product_id = int(request.form.get("product_id") or 0)
        supplier_id = request.form.get("supplier_id") or None
        quantity = int(request.form.get("quantity") or 1)
        unit_cost = float(request.form.get("unit_cost") or 0)
        note = request.form.get("note") or ""
        total = quantity * unit_cost
        if quantity <= 0:
            flash("ژمارە دەبێت زیاتر لە 0 بێت", "danger")
        else:
            conn.execute(
                "INSERT INTO purchases (supplier_id, product_id, quantity, unit_cost, total, note, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (supplier_id, product_id, quantity, unit_cost, total, note, now()),
            )
            conn.execute("UPDATE products SET stock = stock + ?, cost_price = ? WHERE id = ?", (quantity, unit_cost, product_id))
            conn.commit()
            flash("کڕین زیاد کرا و ستۆک زیاد بوو", "success")
        return redirect(url_for("purchases"))

    product_rows = conn.execute("SELECT * FROM products ORDER BY name ASC").fetchall()
    supplier_rows = conn.execute("SELECT * FROM suppliers ORDER BY name ASC").fetchall()
    purchase_rows = conn.execute(
        """
        SELECT pu.*, s.name AS supplier_name, p.name AS product_name
        FROM purchases pu
        LEFT JOIN suppliers s ON s.id = pu.supplier_id
        LEFT JOIN products p ON p.id = pu.product_id
        ORDER BY pu.id DESC LIMIT 50
        """
    ).fetchall()
    conn.close()
    return render_template("purchases.html", products=product_rows, suppliers=supplier_rows, purchases=purchase_rows)


@app.route("/expenses", methods=["GET", "POST"])
@login_required
def expenses():
    conn = get_db()
    if request.method == "POST":
        conn.execute(
            "INSERT INTO expenses (title, amount, category, note, created_at) VALUES (?, ?, ?, ?, ?)",
            (
                request.form.get("title"),
                float(request.form.get("amount") or 0),
                request.form.get("category"),
                request.form.get("note"),
                now(),
            ),
        )
        conn.commit()
        flash("خەرجی زیاد کرا", "success")
        return redirect(url_for("expenses"))
    rows = conn.execute("SELECT * FROM expenses ORDER BY id DESC LIMIT 80").fetchall()
    conn.close()
    return render_template("expenses.html", expenses=rows)


@app.route("/reports")
@login_required
def reports():
    conn = get_db()
    start = request.args.get("start") or today_str()
    end = request.args.get("end") or today_str()

    sales_total = conn.execute(
        "SELECT COALESCE(SUM(total),0) total FROM sales WHERE date(created_at) BETWEEN ? AND ?", (start, end)
    ).fetchone()["total"]
    purchase_total = conn.execute(
        "SELECT COALESCE(SUM(total),0) total FROM purchases WHERE date(created_at) BETWEEN ? AND ?", (start, end)
    ).fetchone()["total"]
    expense_total = conn.execute(
        "SELECT COALESCE(SUM(amount),0) total FROM expenses WHERE date(created_at) BETWEEN ? AND ?", (start, end)
    ).fetchone()["total"]
    profit_estimate = sales_total - purchase_total - expense_total

    best_sellers = conn.execute(
        """
        SELECT p.name, SUM(si.quantity) qty, SUM(si.total) total
        FROM sale_items si
        JOIN products p ON p.id = si.product_id
        JOIN sales s ON s.id = si.sale_id
        WHERE date(s.created_at) BETWEEN ? AND ?
        GROUP BY p.id
        ORDER BY qty DESC
        LIMIT 10
        """,
        (start, end),
    ).fetchall()

    low_stock = conn.execute("SELECT * FROM products WHERE stock <= min_stock ORDER BY stock ASC").fetchall()
    smart_summary = build_smart_summary(sales_total, purchase_total, expense_total, profit_estimate, best_sellers, low_stock)
    conn.close()
    return render_template(
        "reports.html",
        start=start,
        end=end,
        sales_total=sales_total,
        purchase_total=purchase_total,
        expense_total=expense_total,
        profit_estimate=profit_estimate,
        best_sellers=best_sellers,
        low_stock=low_stock,
        smart_summary=smart_summary,
    )


def build_smart_summary(sales_total: float, purchase_total: float, expense_total: float, profit_estimate: float, best_sellers, low_stock) -> list[str]:
    lines: list[str] = []
    if sales_total <= 0:
        lines.append("هیچ فرۆشتنێک لەم ماوەیەدا تۆمار نەکراوە. باشە ڕیکلام یان داشکاندنێکی بچووک تاقی بکەیتەوە.")
    else:
        lines.append(f"کۆی فرۆشتن {money(sales_total)} بووە. ئەمە داتای باشە بۆ ڕاپۆرتی کارگێڕی.")
    if profit_estimate < 0:
        lines.append("ئاگادار بە: قازانجی خەملێندراو نەرێنییە. کڕین و خەرجیەکان پێداچوونەوە پێویستن.")
    elif profit_estimate > 0:
        lines.append(f"قازانجی خەملێندراو {money(profit_estimate)} ـە. ئەگەر ئەمە بەردەوام بێت، کارەکە باش دەڕوات.")
    if best_sellers:
        lines.append(f"زۆرترین کاڵای فرۆشراو: {best_sellers[0]['name']} بە {best_sellers[0]['qty']} دانە.")
    if low_stock:
        lines.append(f"{len(low_stock)} کاڵا ستۆکیان کەمە. پێشنیار: داواکاری کڕین بۆ ئەمانە ئامادە بکە.")
    if expense_total > sales_total and sales_total > 0:
        lines.append("خەرجیەکان لە فرۆشتن زۆرترن. خەرجیەکان بە category جیا بکەوە بۆ دۆزینەوەی کێشە.")
    return lines


if __name__ == "__main__":
    init_db()
    app.run(debug=True, host="0.0.0.0", port=5000)
