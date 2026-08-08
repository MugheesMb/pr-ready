SELECT
    category_id,
    category_name,
    SUM(line_total) AS revenue
FROM {{ ref('order_details') }}
GROUP BY category_id, category_name
ORDER BY revenue DESC