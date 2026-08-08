SELECT
    pc.category_name,
    COUNT(*) AS line_item_count,
    COUNT(DISTINCT oi.order_id) AS order_count,
    SUM(oi.quantity) AS total_units_sold,
    SUM(oi.quantity * oi.unit_price) AS gross_revenue
FROM order_entry_db.order_entry.order_items AS oi
JOIN order_entry_db.order_entry.products AS p
    ON oi.product_id = p.product_id
JOIN order_entry_db.order_entry.product_categories AS pc
    ON p.category_id = pc.category_id
GROUP BY pc.category_name
ORDER BY pc.category_name;