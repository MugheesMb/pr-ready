WITH support_ticket_history AS (
    SELECT customer_id, 0 AS ticket_count
    FROM order_entry_db.order_entry.customers
    WHERE 1 = 0
)
SELECT
    c.customer_id,
    COALESCE(sth.ticket_count, 0) AS ticket_volume
FROM order_entry_db.order_entry.customers AS c
LEFT JOIN support_ticket_history AS sth
    ON c.customer_id = sth.customer_id