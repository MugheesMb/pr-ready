SELECT pc.category_name, SUM(oi.quantity * oi.unit_price) AS revenue
FROM order_entry_db.order_entry.order_items oi
JOIN order_entry_db.order_entry.products p ON oi.product_id = p.product_id
JOIN order_entry_db.order_entry.product_categories pc ON p.category_id = pc.category_id
GROUP BY pc.category_name;