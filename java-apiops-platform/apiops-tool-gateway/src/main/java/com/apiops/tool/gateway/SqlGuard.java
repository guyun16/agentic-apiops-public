package com.apiops.tool.gateway;

import net.sf.jsqlparser.JSQLParserException;
import net.sf.jsqlparser.expression.AnyComparisonExpression;
import net.sf.jsqlparser.expression.Function;
import net.sf.jsqlparser.expression.JdbcNamedParameter;
import net.sf.jsqlparser.expression.JdbcParameter;
import net.sf.jsqlparser.expression.NumericBind;
import net.sf.jsqlparser.expression.ExpressionVisitorAdapter;
import net.sf.jsqlparser.expression.operators.relational.ExistsExpression;
import net.sf.jsqlparser.expression.operators.relational.InExpression;
import net.sf.jsqlparser.expression.LongValue;
import net.sf.jsqlparser.schema.Column;
import net.sf.jsqlparser.schema.Table;
import net.sf.jsqlparser.statement.Statement;
import net.sf.jsqlparser.statement.Statements;
import net.sf.jsqlparser.statement.select.AllColumns;
import net.sf.jsqlparser.statement.select.AllTableColumns;
import net.sf.jsqlparser.statement.select.GroupByElement;
import net.sf.jsqlparser.statement.select.Limit;
import net.sf.jsqlparser.statement.select.OrderByElement;
import net.sf.jsqlparser.statement.select.ParenthesedSelect;
import net.sf.jsqlparser.statement.select.PlainSelect;
import net.sf.jsqlparser.statement.select.SelectItem;
import net.sf.jsqlparser.parser.CCJSqlParserUtil;

import java.math.BigInteger;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Objects;
import java.util.Set;
import java.util.stream.Collectors;

/** AST-based allowlist for the v1 read-only SQL tool. */
public final class SqlGuard implements ResourceGuard {

    public static final String SQL_READ = "sql.read";
    public static final String SQL_ARGUMENT = "sql";
    public static final int MAX_ROWS = 100;

    private static final Set<String> FORBIDDEN_TABLES = Set.of(
            "auth_user",
            "auth_role",
            "auth_authority",
            "apiops_user",
            "apiops_project",
            "apiops_project_member",
            "apiops_role",
            "apiops_authority"
    );

    private final Map<String, Set<String>> allowedColumns;

    public SqlGuard(Map<String, Set<String>> allowedColumns) {
        Objects.requireNonNull(allowedColumns, "allowedColumns must not be null");
        Map<String, Set<String>> normalized = new LinkedHashMap<>();
        allowedColumns.forEach((table, columns) -> {
            String normalizedTable = identifier(table, "table");
            if (FORBIDDEN_TABLES.contains(normalizedTable)) {
                throw new IllegalArgumentException("sensitive table cannot be whitelisted: " + table);
            }
            Objects.requireNonNull(columns, "allowed columns must not be null");
            if (columns.isEmpty()) {
                throw new IllegalArgumentException("allowed columns must not be empty: " + table);
            }
            normalized.put(normalizedTable, columns.stream()
                    .map(column -> identifier(column, "column"))
                    .collect(Collectors.toUnmodifiableSet()));
        });
        this.allowedColumns = Map.copyOf(normalized);
    }

    /** Explicit allowlist for the demo-order-service domain tables. */
    public static SqlGuard demoOrder() {
        return new SqlGuard(Map.of(
                "demo_user", Set.of("id", "user_no", "user_name", "status",
                        "created_at", "updated_at"),
                "demo_product", Set.of("id", "product_no", "product_name", "sale_price",
                        "status", "version", "deleted", "created_at", "updated_at"),
                "demo_inventory", Set.of("id", "product_id", "available_stock",
                        "created_at", "updated_at"),
                "demo_coupon", Set.of("id", "coupon_no", "coupon_name", "threshold_amount",
                        "discount_amount", "valid_from", "valid_until", "status", "deleted",
                        "created_at", "updated_at"),
                "demo_user_coupon", Set.of("id", "user_coupon_no", "user_id", "coupon_id",
                        "status", "received_at", "used_at", "created_at", "updated_at"),
                "demo_order", Set.of("id", "order_no", "user_id", "user_coupon_id",
                        "original_amount", "discount_amount", "payable_amount", "status",
                        "created_at", "updated_at"),
                "demo_order_item", Set.of("id", "order_id", "product_id", "product_no_snapshot",
                        "product_name_snapshot", "unit_price", "quantity", "line_amount",
                        "created_at", "updated_at"),
                "demo_payment", Set.of("id", "payment_no", "order_id", "payment_amount",
                        "status", "paid_at", "created_at", "updated_at"),
                "demo_payment_callback", Set.of("id", "callback_no", "payment_id",
                        "callback_amount", "request_fingerprint", "process_status", "result_code",
                        "result_message", "received_at", "processed_at", "created_at", "updated_at")
        ));
    }

    @Override
    public Decision check(
            ToolExecutionContext context,
            ToolDefinition definition,
            ToolCallIntent intent
    ) {
        if (definition == null || !SQL_READ.equals(definition.name())) {
            return Decision.allow();
        }
        Validation validation = validate(intent);
        return validation.allowed()
                ? Decision.allow()
                : Decision.reject(validation.reason());
    }

    public Validation validate(ToolCallIntent intent) {
        if (intent == null) {
            return Validation.denied("SQL tool intent is required");
        }
        Object value = intent.arguments().get(SQL_ARGUMENT);
        if (!(value instanceof String sql) || sql.isBlank()) {
            return Validation.denied("sql argument is required");
        }
        return validateSql(sql);
    }

    public Validation validateSql(String sql) {
        if (sql == null || sql.isBlank()) {
            return Validation.denied("sql must not be blank");
        }
        try {
            Statements statements = CCJSqlParserUtil.parseStatements(sql);
            if (statements.size() != 1) {
                throw rejected("only one SQL statement is allowed");
            }
            Statement statement = statements.get(0);
            if (!(statement instanceof PlainSelect plainSelect)) {
                throw rejected("only a single plain SELECT is allowed");
            }
            return validatePlainSelect(plainSelect);
        } catch (JSQLParserException | GuardRejection exception) {
            return Validation.denied(exception.getMessage());
        } catch (RuntimeException exception) {
            return Validation.denied("SQL AST validation failed");
        }
    }

    public Map<String, Set<String>> allowedColumns() {
        return allowedColumns;
    }

    private Validation validatePlainSelect(PlainSelect select) {
        if (select.getWithItemsList() != null && !select.getWithItemsList().isEmpty()) {
            throw rejected("CTE is not allowed");
        }
        if (select.getJoins() != null && !select.getJoins().isEmpty()) {
            throw rejected("JOIN is not allowed");
        }
        if (select.getFromItem() == null || !(select.getFromItem() instanceof Table table)) {
            throw rejected("subquery and non-table sources are not allowed");
        }
        if (select.getIntoTables() != null && !select.getIntoTables().isEmpty()
                || select.getIntoTempTable() != null) {
            throw rejected("SELECT INTO is not allowed");
        }
        if (select.getForMode() != null
                || select.getForUpdateTable() != null
                || select.getForClause() != null
                || select.getWait() != null
                || select.isSkipLocked()) {
            throw rejected("locking SELECT is not allowed");
        }
        if (select.getFetch() != null || select.getLimitBy() != null) {
            throw rejected("unsupported row limiting syntax");
        }

        String tableName = identifier(table.getUnquotedName(), "table");
        if (table.getSchemaName() != null && !table.getSchemaName().isBlank()
                || table.getDatabaseName() != null && !table.getDatabaseName().isBlank()
                || table.getCatalogName() != null && !table.getCatalogName().isBlank()) {
            throw rejected("qualified table names are not allowed");
        }
        if (FORBIDDEN_TABLES.contains(tableName)) {
            throw rejected("sensitive table is forbidden: " + tableName);
        }
        Set<String> columns = allowedColumns.get(tableName);
        if (columns == null) {
            throw rejected("table is not allowlisted: " + tableName);
        }

        Set<String> qualifiers = Set.of(tableName);
        if (table.getAlias() != null && table.getAlias().getName() != null) {
            LinkedHashSet<String> aliases = new LinkedHashSet<>();
            aliases.add(tableName);
            aliases.add(identifier(table.getAlias().getName(), "table alias"));
            qualifiers = aliases;
        }
        ColumnVisitor visitor = new ColumnVisitor(columns, qualifiers);
        List<SelectItem<?>> selectItems = select.getSelectItems();
        if (selectItems == null || selectItems.isEmpty()) {
            throw rejected("SELECT list must not be empty");
        }
        for (SelectItem<?> item : selectItems) {
            if (item == null || item.getExpression() == null) {
                throw rejected("invalid SELECT item");
            }
            item.getExpression().accept(visitor, null);
        }
        visit(visitor, select.getWhere());
        visit(visitor, select.getHaving());
        visitGroupBy(visitor, select.getGroupBy());
        if (select.getOrderByElements() != null) {
            for (OrderByElement orderBy : select.getOrderByElements()) {
                visit(visitor, orderBy.getExpression());
            }
        }

        Limit limit = boundedLimit(select);
        return Validation.allowed(select.toString());
    }

    private static void visit(ColumnVisitor visitor,
                              net.sf.jsqlparser.expression.Expression expression) {
        if (expression != null) {
            expression.accept(visitor, null);
        }
    }

    private static void visitGroupBy(ColumnVisitor visitor, GroupByElement groupBy) {
        if (groupBy == null) {
            return;
        }
        visit(visitor, groupBy.getGroupByExpressionList());
        visit(visitor, groupBy.getGroupByExpressions());
        if (groupBy.getGroupingSets() != null) {
            groupBy.getGroupingSets().forEach(expressionList -> visit(visitor, expressionList));
        }
    }

    private static Limit boundedLimit(PlainSelect select) {
        Limit limit = select.getLimit();
        if (limit == null) {
            select.setLimit(new Limit().withRowCount(new LongValue(MAX_ROWS)));
            return select.getLimit();
        }
        if (limit.isLimitAll() || !(limit.getRowCount() instanceof LongValue rowCount)) {
            throw rejected("LIMIT must be a numeric row count");
        }
        BigInteger count = rowCount.getBigIntegerValue();
        if (count.signum() < 0) {
            throw rejected("LIMIT must not be negative");
        }
        if (count.compareTo(BigInteger.valueOf(MAX_ROWS)) > 0) {
            limit.setRowCount(new LongValue(MAX_ROWS));
        }
        if (limit.getOffset() != null && !(limit.getOffset() instanceof LongValue)) {
            throw rejected("LIMIT offset must be numeric");
        }
        return limit;
    }

    private static String identifier(String value, String kind) {
        Objects.requireNonNull(value, kind + " must not be null");
        String normalized = value.trim().toLowerCase(Locale.ROOT);
        if (normalized.isBlank()) {
            throw new IllegalArgumentException(kind + " must not be blank");
        }
        return normalized;
    }

    private static GuardRejection rejected(String reason) {
        return new GuardRejection(reason);
    }

    public record Validation(boolean allowed, String reason, String boundedSql) {

        public Validation {
            Objects.requireNonNull(reason, "reason must not be null");
            if (allowed && (boundedSql == null || boundedSql.isBlank())) {
                throw new IllegalArgumentException("allowed SQL must be present");
            }
            if (!allowed && boundedSql != null) {
                throw new IllegalArgumentException("denied SQL must not have an executable form");
            }
        }

        private static Validation denied(String reason) {
            return new Validation(false, reason, null);
        }

        private static Validation allowed(String boundedSql) {
            return new Validation(true, "allowed", boundedSql);
        }
    }

    private static final class ColumnVisitor extends ExpressionVisitorAdapter<Void> {

        private final Set<String> allowedColumns;
        private final Set<String> qualifiers;

        private ColumnVisitor(Set<String> allowedColumns, Set<String> qualifiers) {
            this.allowedColumns = allowedColumns;
            this.qualifiers = qualifiers;
        }

        @Override
        public <S> Void visit(Column column, S context) {
            String qualifier = column.getTableName();
            if (qualifier != null && !qualifier.isBlank()
                    && !qualifiers.contains(identifier(qualifier, "column qualifier"))) {
                throw rejected("column qualifier is not allowed: " + qualifier);
            }
            String columnName = identifier(column.getUnquotedColumnName(), "column");
            if (!allowedColumns.contains(columnName)) {
                throw rejected("column is not allowlisted: " + columnName);
            }
            return null;
        }

        @Override
        public <S> Void visit(AllColumns columns, S context) {
            throw rejected("SELECT * is not allowed");
        }

        @Override
        public <S> Void visit(AllTableColumns columns, S context) {
            throw rejected("SELECT table.* is not allowed");
        }

        @Override
        public <S> Void visit(ParenthesedSelect select, S context) {
            throw rejected("subquery is not allowed");
        }

        @Override
        public <S> Void visit(AnyComparisonExpression expression, S context) {
            throw rejected("subquery comparison is not allowed");
        }

        @Override
        public <S> Void visit(ExistsExpression expression, S context) {
            throw rejected("subquery is not allowed");
        }

        @Override
        public <S> Void visit(InExpression expression, S context) {
            if (expression.getRightExpression() instanceof ParenthesedSelect) {
                throw rejected("subquery is not allowed");
            }
            return super.visit(expression, context);
        }

        @Override
        public <S> Void visit(Function function, S context) {
            throw rejected("SQL functions are not allowed in v1");
        }

        @Override
        public <S> Void visit(JdbcParameter parameter, S context) {
            throw rejected("JDBC parameters are not supported");
        }

        @Override
        public <S> Void visit(JdbcNamedParameter parameter, S context) {
            throw rejected("named parameters are not supported");
        }

        @Override
        public <S> Void visit(NumericBind parameter, S context) {
            throw rejected("numeric parameters are not supported");
        }
    }

    private static final class GuardRejection extends RuntimeException {
        private GuardRejection(String message) {
            super(message);
        }
    }
}
