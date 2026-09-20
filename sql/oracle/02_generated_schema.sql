-- ARQUIVO GERADO - NAO EDITAR A MAO.
-- Regenere este arquivo executando generate_oracle_ddl.py.
-- Constraints, indices e regras de negocio ficam em 03_constraints_and_indexes.sql.

CREATE TABLE addresses (
    id NUMBER(10),
    customer_id NUMBER(10),
    address_type VARCHAR2(10 CHAR),
    postal_code VARCHAR2(10 CHAR),
    street VARCHAR2(50 CHAR),
    address_number VARCHAR2(5 CHAR),
    complement VARCHAR2(10 CHAR),
    district VARCHAR2(50 CHAR),
    city VARCHAR2(50 CHAR),
    state VARCHAR2(2 CHAR),
    country VARCHAR2(2 CHAR),
    is_primary NUMBER(1)
);

CREATE TABLE attributes (
    id NUMBER(10),
    name VARCHAR2(10 CHAR),
    data_type VARCHAR2(10 CHAR)
);

CREATE TABLE brands (
    id NUMBER(10),
    name VARCHAR2(20 CHAR),
    country VARCHAR2(2 CHAR),
    is_active NUMBER(1),
    created_at DATE,
    updated_at DATE
);

CREATE TABLE categories (
    id NUMBER(10),
    name VARCHAR2(20 CHAR),
    slug VARCHAR2(20 CHAR),
    parent_category_id NUMBER(10),
    is_active NUMBER(1),
    created_at DATE,
    updated_at DATE
);

CREATE TABLE customers (
    id NUMBER(10),
    person_type VARCHAR2(2 CHAR),
    legal_name VARCHAR2(50 CHAR),
    trade_name VARCHAR2(50 CHAR),
    tax_id VARCHAR2(20 CHAR),
    state_registration VARCHAR2(10 CHAR),
    email VARCHAR2(50 CHAR),
    phone VARCHAR2(20 CHAR),
    is_active NUMBER(1),
    created_at DATE,
    updated_at DATE
);

CREATE TABLE employees (
    id NUMBER(10),
    full_name VARCHAR2(50 CHAR),
    cpf VARCHAR2(20 CHAR),
    email VARCHAR2(50 CHAR),
    role VARCHAR2(20 CHAR),
    primary_location_id NUMBER(10),
    hire_date DATE,
    termination_date DATE,
    is_active NUMBER(1),
    created_at DATE,
    updated_at DATE
);

CREATE TABLE fiscal_invoices (
    id NUMBER(10),
    order_id NUMBER(10),
    nfe_number VARCHAR2(20 CHAR),
    nfe_access_key VARCHAR2(50 CHAR),
    series NUMBER(10),
    issued_at DATE,
    status VARCHAR2(10 CHAR),
    total_amount NUMBER(12, 2),
    xml_storage_uri VARCHAR2(100 CHAR),
    created_at DATE,
    updated_at DATE
);

CREATE TABLE goods_receipt_items (
    id NUMBER(10),
    goods_receipt_id NUMBER(10),
    purchase_order_item_id NUMBER(10),
    quantity_received NUMBER(9, 3)
);

CREATE TABLE goods_receipts (
    id NUMBER(10),
    purchase_order_id NUMBER(10),
    received_by_employee_id NUMBER(10),
    received_at DATE,
    notes VARCHAR2(20 CHAR),
    created_at DATE
);

CREATE TABLE locations (
    id NUMBER(10),
    name VARCHAR2(20 CHAR),
    location_type VARCHAR2(10 CHAR),
    postal_code VARCHAR2(10 CHAR),
    street VARCHAR2(50 CHAR),
    location_number VARCHAR2(5 CHAR),
    complement VARCHAR2(10 CHAR),
    district VARCHAR2(50 CHAR),
    city VARCHAR2(20 CHAR),
    state VARCHAR2(2 CHAR),
    country VARCHAR2(2 CHAR),
    is_active NUMBER(1),
    created_at DATE,
    updated_at DATE
);

CREATE TABLE order_items (
    id NUMBER(10),
    order_id NUMBER(10),
    product_variant_id NUMBER(10),
    quantity NUMBER(10),
    unit_price NUMBER(10, 2),
    icms_rate NUMBER(10),
    ipi_rate NUMBER(10),
    line_total NUMBER(11, 2)
);

CREATE TABLE orders (
    id NUMBER(10),
    order_number VARCHAR2(10 CHAR),
    channel VARCHAR2(10 CHAR),
    customer_id NUMBER(10),
    salesperson_id NUMBER(10),
    location_id NUMBER(10),
    status VARCHAR2(10 CHAR),
    subtotal NUMBER(12, 2),
    discount_amount NUMBER(11, 2),
    total NUMBER(12, 2),
    placed_at DATE,
    created_at DATE,
    updated_at DATE
);

CREATE TABLE payments (
    id NUMBER(10),
    order_id NUMBER(10),
    method VARCHAR2(20 CHAR),
    installments NUMBER(10),
    amount NUMBER(12, 2),
    status VARCHAR2(10 CHAR),
    paid_at DATE,
    created_at DATE,
    updated_at DATE
);

CREATE TABLE product_suppliers (
    product_variant_id NUMBER(10),
    supplier_id NUMBER(10),
    supplier_sku VARCHAR2(20 CHAR),
    last_quoted_cost NUMBER(10, 2),
    lead_time_days NUMBER(10),
    is_preferred NUMBER(1),
    created_at DATE,
    updated_at DATE
);

CREATE TABLE product_variants (
    id NUMBER(10),
    product_id NUMBER(10),
    sku VARCHAR2(10 CHAR),
    barcode_ean VARCHAR2(20 CHAR),
    sale_price NUMBER(10, 2),
    cost_price NUMBER(10, 2),
    weight_kg NUMBER(9, 3),
    icms_rate NUMBER(10),
    ipi_rate NUMBER(10),
    is_active NUMBER(1),
    created_at DATE,
    updated_at DATE
);

CREATE TABLE products (
    id NUMBER(10),
    name VARCHAR2(50 CHAR),
    description VARCHAR2(50 CHAR),
    brand_id NUMBER(10),
    category_id NUMBER(10),
    ncm_code VARCHAR2(10 CHAR),
    unit_of_measure VARCHAR2(2 CHAR),
    is_active NUMBER(1),
    created_at DATE,
    updated_at DATE
);

CREATE TABLE purchase_order_items (
    id NUMBER(10),
    purchase_order_id NUMBER(10),
    product_variant_id NUMBER(10),
    quantity_ordered NUMBER(10),
    unit_cost NUMBER(10, 2),
    line_total NUMBER(12, 2)
);

CREATE TABLE purchase_orders (
    id NUMBER(10),
    po_number VARCHAR2(10 CHAR),
    supplier_id NUMBER(10),
    buyer_id NUMBER(10),
    destination_location_id NUMBER(10),
    status VARCHAR2(20 CHAR),
    currency VARCHAR2(5 CHAR),
    subtotal NUMBER(12, 2),
    total NUMBER(12, 2),
    placed_at DATE,
    expected_delivery_at DATE,
    created_at DATE,
    updated_at DATE
);

CREATE TABLE return_items (
    id NUMBER(10),
    return_id NUMBER(10),
    order_item_id NUMBER(10),
    quantity NUMBER(10),
    action VARCHAR2(10 CHAR),
    exchange_variant_id NUMBER(10),
    unit_refund_amount NUMBER(10, 2)
);

CREATE TABLE returns (
    id NUMBER(10),
    return_number VARCHAR2(10 CHAR),
    order_id NUMBER(10),
    customer_id NUMBER(10),
    received_at_location_id NUMBER(10),
    status VARCHAR2(10 CHAR),
    reason VARCHAR2(50 CHAR),
    total_refund_amount NUMBER(11, 2),
    created_at DATE,
    updated_at DATE
);

CREATE TABLE stock_levels (
    product_variant_id NUMBER(10),
    location_id NUMBER(10),
    quantity_on_hand NUMBER(9, 3),
    reorder_point VARCHAR2(1 CHAR),
    updated_at DATE
);

CREATE TABLE stock_movements (
    id NUMBER(10),
    product_variant_id NUMBER(10),
    location_id NUMBER(10),
    movement_type VARCHAR2(20 CHAR),
    quantity NUMBER(10, 3),
    reference_table VARCHAR2(20 CHAR),
    reference_id NUMBER(10),
    employee_id NUMBER(10),
    notes VARCHAR2(50 CHAR),
    occurred_at DATE,
    created_at DATE
);

CREATE TABLE suppliers (
    id NUMBER(10),
    legal_name VARCHAR2(50 CHAR),
    trade_name VARCHAR2(20 CHAR),
    country VARCHAR2(2 CHAR),
    tax_id VARCHAR2(20 CHAR),
    tax_id_type VARCHAR2(5 CHAR),
    email VARCHAR2(50 CHAR),
    phone VARCHAR2(20 CHAR),
    contact_name VARCHAR2(50 CHAR),
    is_active NUMBER(1),
    created_at DATE,
    updated_at DATE
);

CREATE TABLE variant_attribute_values (
    product_variant_id NUMBER(10),
    attribute_id NUMBER(10),
    variant_attribute_value_value VARCHAR2(20 CHAR)
);
