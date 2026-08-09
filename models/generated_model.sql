SELECT
    category_name,
    SUM(line_total) AS category_revenue,
    COUNT(DISTINCT order_id) AS order_count
FROM {{ ref('order_details') }}
GROUP BY category_name
ORDER BY category_revenue DESC