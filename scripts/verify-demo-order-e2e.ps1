$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
$javaRoot = Join-Path $repoRoot "java-apiops-platform"
$moduleRoot = Join-Path $javaRoot "apiops-demo-order-service"
$runtimeDir = Join-Path $moduleRoot "target\runtime-verification\e2e-script"
$helperDir = Join-Path $runtimeDir "jdbc-helper"

if (-not (Test-Path (Join-Path $javaRoot "mvnw.cmd"))) {
    throw "Maven root not found: java-apiops-platform"
}

$localConfigPath = Join-Path $moduleRoot "src\main\resources\application-local.yml"
$localConfig = Get-Content -LiteralPath $localConfigPath -Raw
$dbEnvNames = @(
    [regex]::Matches($localConfig, '\$\{([A-Z][A-Z0-9_]*)') |
        ForEach-Object { $_.Groups[1].Value } |
        Select-Object -Unique
)

$missingEnv = @($dbEnvNames | Where-Object {
        [string]::IsNullOrWhiteSpace([Environment]::GetEnvironmentVariable($_))
    })
if ($missingEnv.Count -gt 0) {
    Write-Error ("Missing required database environment variables: " + ($missingEnv -join ", "))
    exit 2
}

New-Item -ItemType Directory -Path $runtimeDir -Force | Out-Null
New-Item -ItemType Directory -Path $helperDir -Force | Out-Null

$jarPattern = '(?i)apiops-demo-order-service-[^\s"]+\.jar'
$startedProcess = $null
$startedProcessId = $null
$baseUrl = $null
$activeResources = [System.Collections.ArrayList]::new()
$cleanupErrors = [System.Collections.ArrayList]::new()
$scriptFailure = $null

function Get-TargetJar {
    $jar = Get-ChildItem -LiteralPath (Join-Path $moduleRoot "target") -Filter "apiops-demo-order-service-*.jar" -File |
        Where-Object { $_.Name -notlike "*.original" } |
        Sort-Object LastWriteTime -Descending |
        Select-Object -First 1
    if ($null -eq $jar) {
        throw "Executable apiops-demo-order-service JAR was not found after verify"
    }
    return $jar
}

function Get-ModuleJarProcesses([string]$jarName) {
    $pattern = [regex]::Escape($jarName)
    return @(Get-CimInstance Win32_Process -Filter "Name = 'java.exe' OR Name = 'javaw.exe'" |
        Where-Object { $_.CommandLine -match $pattern })
}

function Invoke-DbProbe([string[]]$Arguments) {
    $output = & java.exe -cp ("{0}{1}{2}" -f $helperDir, [IO.Path]::PathSeparator, $driverJar) E2eDbProbe @Arguments 2>&1
    if ($LASTEXITCODE -ne 0) {
        throw "JDBC probe failed: $($output -join [Environment]::NewLine)"
    }
    $values = @{}
    foreach ($line in $output) {
        if ($line -match '^([A-Z0-9_]+)=(.*)$') {
            $values[$Matches[1]] = $Matches[2]
        }
    }
    return $values
}

function As-Long([hashtable]$Values, [string]$Key) {
    return [int64]$Values[$Key]
}

function As-Decimal([hashtable]$Values, [string]$Key) {
    return [decimal]$Values[$Key]
}

function Assert-Equal($Actual, $Expected, [string]$Label) {
    if ([string]$Actual -ne [string]$Expected) {
        throw "$Label expected '$Expected' but was '$Actual'"
    }
}

function Assert-True([bool]$Condition, [string]$Label) {
    if (-not $Condition) {
        throw "Assertion failed: $Label"
    }
}

function Assert-Null($Value, [string]$Label) {
    if ($null -ne $Value) {
        throw "Assertion failed: $Label was not null"
    }
}

function Save-Json([string]$Name, $Value) {
    $path = Join-Path $runtimeDir $Name
    $Value | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath $path -Encoding utf8
    return $path
}

function Invoke-Api([string]$Method, [string]$Path, [string]$Name, [string]$BodyPath) {
    $responsePath = Join-Path $runtimeDir ("{0}-response.json" -f $Name)
    $curlErrorPath = Join-Path $runtimeDir ("{0}-curl-error.log" -f $Name)
    $arguments = @("-sS", "-o", $responsePath, "-w", "%{http_code}", "-X", $Method, ("{0}{1}" -f $baseUrl, $Path))
    if (-not [string]::IsNullOrWhiteSpace($BodyPath)) {
        $arguments += @("-H", "Content-Type: application/json", "--data-binary", ("@{0}" -f $BodyPath))
    }
    $stopwatch = [Diagnostics.Stopwatch]::StartNew()
    $statusText = & curl.exe @arguments 2> $curlErrorPath
    $stopwatch.Stop()
    if ($LASTEXITCODE -ne 0) {
        throw "HTTP request failed for $Method ${Path}: $(Get-Content -LiteralPath $curlErrorPath -Raw)"
    }
    $bodyText = Get-Content -LiteralPath $responsePath -Raw
    $json = $bodyText | ConvertFrom-Json
    return [pscustomobject]@{
        Method = $Method
        Path = $Path
        Status = [int]$statusText.Trim()
        Body = $json
        BodyText = $bodyText
        ResponsePath = $responsePath
        ClientElapsedMs = [math]::Round($stopwatch.Elapsed.TotalMilliseconds, 3)
    }
}

function Assert-ApiEnvelope($Response, [int]$Status, [bool]$Success, [string]$Code, [string]$Label) {
    Assert-Equal $Response.Status $Status "$Label HTTP status"
    Assert-Equal $Response.Body.success $Success "$Label success"
    Assert-Equal $Response.Body.code $Code "$Label code"
}

function Get-Snapshot([hashtable]$Ids) {
    return Invoke-DbProbe @(
        "snapshot",
        $Ids.USER_ID,
        $Ids.PRODUCT1_ID,
        $Ids.PRODUCT2_ID,
        $Ids.COUPON_ID,
        $Ids.USER_COUPON_ID
    )
}

function Register-Resource([hashtable]$Resource) {
    [void]$activeResources.Add($Resource)
}

function Remove-Resource([hashtable]$Resource) {
    [void]$activeResources.Remove($Resource)
}

function Cleanup-Resource([hashtable]$Resource) {
    if ($null -eq $Resource -or -not $Resource.ContainsKey("ORDER_ID")) {
        return
    }
    $callbackId = if ($Resource.ContainsKey("CALLBACK_ID")) { $Resource.CALLBACK_ID } else { "-" }
    $paymentId = if ($Resource.ContainsKey("PAYMENT_ID")) { $Resource.PAYMENT_ID } else { 0 }
    $userCouponId = if ($Resource.ContainsKey("USER_COUPON_ID")) { $Resource.USER_COUPON_ID } else { 0 }
    $couponStatus = if ($Resource.ContainsKey("COUPON_STATUS")) { $Resource.COUPON_STATUS } else { "-" }
    $couponUsedAt = if ($Resource.ContainsKey("COUPON_USED_AT")) { $Resource.COUPON_USED_AT } else { "NULL" }
    [void](Invoke-DbProbe @(
        "cleanup",
        $Resource.ORDER_ID,
        $paymentId,
        $callbackId,
        $Resource.PRODUCT_ID,
        $Resource.INVENTORY_BEFORE,
        $userCouponId,
        $couponStatus,
        $couponUsedAt
    ))
    Remove-Resource $Resource
}

function Assert-CountsUnchanged([hashtable]$Before, [hashtable]$After, [string]$Label) {
    foreach ($key in @("ORDER_COUNT", "ITEM_COUNT", "PAYMENT_COUNT", "CALLBACK_COUNT")) {
        Assert-Equal $After[$key] $Before[$key] "$Label $key"
    }
}

function Assert-OrderState([hashtable]$Order, [string]$Status, [int64]$OrderId, [decimal]$PayableAmount) {
    Assert-Equal $Order.ORDER_ID $OrderId "order id"
    Assert-Equal $Order.ORDER_STATUS $Status "order status"
    Assert-Equal ([decimal]$Order.PAYABLE_AMOUNT) $PayableAmount "order payable amount"
}

try {
    Push-Location $javaRoot
    try {
        $buildOutput = & .\mvnw.cmd clean verify 2>&1
        $buildExitCode = $LASTEXITCODE
    }
    finally {
        Pop-Location
    }
    if ($buildExitCode -ne 0) {
        $buildOutput | Write-Output
        throw "clean verify failed with exit code $buildExitCode"
    }

    $reports = @()
    foreach ($module in @("apiops-common", "apiops-web", "apiops-demo-order-service")) {
        $moduleReports = Get-ChildItem -LiteralPath (Join-Path $javaRoot $module) -Recurse -Filter "TEST-*.xml" -File -ErrorAction SilentlyContinue
        $tests = 0; $failures = 0; $errors = 0; $skipped = 0
        foreach ($report in $moduleReports) {
            [xml]$xml = Get-Content -LiteralPath $report.FullName -Raw
            $suite = $xml.testsuite
            $tests += [int]$suite.tests
            $failures += [int]$suite.failures
            $errors += [int]$suite.errors
            $skipped += [int]$suite.skipped
        }
        $reports += [pscustomobject]@{ Module = $module; Tests = $tests; Failures = $failures; Errors = $errors; Skipped = $skipped }
    }
    $reports | ForEach-Object { Write-Output ("TESTS {0}: Tests={1}, Failures={2}, Errors={3}, Skipped={4}" -f $_.Module, $_.Tests, $_.Failures, $_.Errors, $_.Skipped) }
    $totalTests = ($reports | Measure-Object -Property Tests -Sum).Sum
    $totalFailures = ($reports | Measure-Object -Property Failures -Sum).Sum
    $totalErrors = ($reports | Measure-Object -Property Errors -Sum).Sum
    $totalSkipped = ($reports | Measure-Object -Property Skipped -Sum).Sum
    Write-Output ("TESTS TOTAL: Tests={0}, Failures={1}, Errors={2}, Skipped={3}" -f $totalTests, $totalFailures, $totalErrors, $totalSkipped)

    New-Item -ItemType Directory -Path $runtimeDir -Force | Out-Null
    New-Item -ItemType Directory -Path $helperDir -Force | Out-Null
    $jar = Get-TargetJar
    $existing = @(Get-ModuleJarProcesses $jar.Name)
    if ($existing.Count -gt 0) {
        throw "Matching module JAR process exists before startup"
    }

    $driverJar = Get-ChildItem -LiteralPath (Join-Path $env:USERPROFILE ".m2\repository\com\mysql\mysql-connector-j") -Recurse -Filter "mysql-connector-j-*.jar" -File |
        Where-Object { $_.Name -notmatch "(sources|javadoc)" } |
        Sort-Object LastWriteTime -Descending |
        Select-Object -First 1 -ExpandProperty FullName
    if ([string]::IsNullOrWhiteSpace($driverJar)) {
        throw "MySQL Connector/J was not found in the local Maven repository"
    }

    $helperSource = @'
import java.math.BigDecimal;
import java.sql.*;

public class E2eDbProbe {
    private static Connection open() throws SQLException {
        try { Class.forName("com.mysql.cj.jdbc.Driver"); } catch (ClassNotFoundException e) { throw new SQLException("MySQL Connector/J driver is unavailable", e); }
        return DriverManager.getConnection(
                System.getenv("APIOPS_ORDER_DB_URL"),
                System.getenv("APIOPS_ORDER_DB_USERNAME"),
                System.getenv("APIOPS_ORDER_DB_PASSWORD"));
    }

    private static String value(ResultSet rs, int index) throws SQLException {
        String value = rs.getString(index);
        return value == null ? "NULL" : value;
    }

    private static void out(String key, Object value) {
        System.out.println(key + "=" + (value == null ? "NULL" : value));
    }

    private static void lookup(Connection c) throws Exception {
        try (PreparedStatement ps = c.prepareStatement("SELECT id FROM demo_user WHERE user_no=?")) {
            ps.setString(1, "usr_001");
            try (ResultSet rs = ps.executeQuery()) { if (!rs.next()) throw new IllegalStateException("usr_001 not found"); out("USER_ID", rs.getLong(1)); }
        }
        product(c, "prd_001", "PRODUCT1");
        product(c, "prd_002", "PRODUCT2");
        try (PreparedStatement ps = c.prepareStatement("SELECT id, threshold_amount, discount_amount FROM demo_coupon WHERE coupon_no=? AND deleted=0")) {
            ps.setString(1, "cpn_001");
            try (ResultSet rs = ps.executeQuery()) { if (!rs.next()) throw new IllegalStateException("cpn_001 not found"); out("COUPON_ID", rs.getLong(1)); out("COUPON_THRESHOLD", rs.getBigDecimal(2)); out("COUPON_DISCOUNT", rs.getBigDecimal(3)); }
        }
        long userId = number(c, "SELECT id FROM demo_user WHERE user_no='usr_001'");
        long couponId = number(c, "SELECT id FROM demo_coupon WHERE coupon_no='cpn_001' AND deleted=0");
        userCoupon(c, userId, couponId);
        out("MISSING_PRODUCT_ID", number(c, "SELECT COALESCE(MAX(id),0)+1 FROM demo_product"));
        counts(c);
    }

    private static void product(Connection c, String productNo, String prefix) throws Exception {
        try (PreparedStatement ps = c.prepareStatement("SELECT p.id,p.sale_price,p.status,i.available_stock FROM demo_product p JOIN demo_inventory i ON i.product_id=p.id WHERE p.product_no=?")) {
            ps.setString(1, productNo);
            try (ResultSet rs = ps.executeQuery()) { if (!rs.next()) throw new IllegalStateException(productNo + " not found"); out(prefix + "_ID", rs.getLong(1)); out(prefix + "_PRICE", rs.getBigDecimal(2)); out(prefix + "_STATUS", rs.getString(3)); out(prefix + "_STOCK", rs.getLong(4)); }
        }
    }

    private static void userCoupon(Connection c, long userId, long couponId) throws Exception {
        try (PreparedStatement ps = c.prepareStatement("SELECT id,status,COALESCE(DATE_FORMAT(used_at,'%Y-%m-%dT%H:%i:%s.%f'),'NULL') FROM demo_user_coupon WHERE user_id=? AND coupon_id=?")) {
            ps.setLong(1, userId); ps.setLong(2, couponId);
            try (ResultSet rs = ps.executeQuery()) { if (!rs.next()) throw new IllegalStateException("user coupon not found"); out("USER_COUPON_ID", rs.getLong(1)); out("USER_COUPON_STATUS", rs.getString(2)); out("USER_COUPON_USED_AT", value(rs,3)); }
        }
    }

    private static long number(Connection c, String sql) throws Exception { try (Statement s=c.createStatement(); ResultSet rs=s.executeQuery(sql)) { if (!rs.next()) throw new IllegalStateException("no result"); return rs.getLong(1); } }

    private static void counts(Connection c) throws Exception { out("ORDER_COUNT", number(c,"SELECT COUNT(*) FROM demo_order")); out("ITEM_COUNT", number(c,"SELECT COUNT(*) FROM demo_order_item")); out("PAYMENT_COUNT", number(c,"SELECT COUNT(*) FROM demo_payment")); out("CALLBACK_COUNT", number(c,"SELECT COUNT(*) FROM demo_payment_callback")); }

    private static void snapshot(Connection c, String[] a) throws Exception {
        long p1=Long.parseLong(a[2]), p2=Long.parseLong(a[3]), coupon=Long.parseLong(a[4]), userCoupon=Long.parseLong(a[5]);
        out("PRODUCT1_STOCK", number(c,"SELECT available_stock FROM demo_inventory WHERE product_id="+p1));
        out("PRODUCT2_STOCK", number(c,"SELECT available_stock FROM demo_inventory WHERE product_id="+p2));
        out("USER_COUPON_STATUS", text(c,"SELECT status FROM demo_user_coupon WHERE id="+userCoupon));
        out("USER_COUPON_USED_AT", text(c,"SELECT COALESCE(DATE_FORMAT(used_at,'%Y-%m-%dT%H:%i:%s.%f'),'NULL') FROM demo_user_coupon WHERE id="+userCoupon));
        counts(c);
    }

    private static String text(Connection c, String sql) throws Exception { try (Statement s=c.createStatement(); ResultSet rs=s.executeQuery(sql)) { if (!rs.next()) throw new IllegalStateException("no result"); return rs.getString(1); } }

    private static void order(Connection c, String[] a) throws Exception {
        long id=Long.parseLong(a[1]);
        try (PreparedStatement ps=c.prepareStatement("SELECT id,user_id,COALESCE(user_coupon_id,0),original_amount,discount_amount,payable_amount,status,DATE_FORMAT(updated_at,'%Y-%m-%dT%H:%i:%s.%f') FROM demo_order WHERE id=?")) { ps.setLong(1,id); try(ResultSet rs=ps.executeQuery()){ if(!rs.next()) throw new IllegalStateException("order not found"); out("ORDER_ID",rs.getLong(1)); out("ORDER_USER_ID",rs.getLong(2)); out("ORDER_USER_COUPON_ID",rs.getLong(3)); out("ORIGINAL_AMOUNT",rs.getBigDecimal(4)); out("DISCOUNT_AMOUNT",rs.getBigDecimal(5)); out("PAYABLE_AMOUNT",rs.getBigDecimal(6)); out("ORDER_STATUS",rs.getString(7)); out("ORDER_UPDATED_AT",rs.getString(8)); }}
        out("ITEM_COUNT_FOR_ORDER", number(c,"SELECT COUNT(*) FROM demo_order_item WHERE order_id="+id));
        out("PAYMENT_COUNT_FOR_ORDER", number(c,"SELECT COUNT(*) FROM demo_payment WHERE order_id="+id));
        try (PreparedStatement ps=c.prepareStatement("SELECT product_id,quantity,unit_price,line_amount FROM demo_order_item WHERE order_id=? ORDER BY id")){ps.setLong(1,id);try(ResultSet rs=ps.executeQuery()){if(rs.next()){out("ITEM_PRODUCT_ID",rs.getLong(1));out("ITEM_QUANTITY",rs.getInt(2));out("ITEM_UNIT_PRICE",rs.getBigDecimal(3));out("ITEM_LINE_AMOUNT",rs.getBigDecimal(4));}}}
        try (PreparedStatement ps=c.prepareStatement("SELECT id,payment_amount,status,COALESCE(DATE_FORMAT(paid_at,'%Y-%m-%dT%H:%i:%s.%f'),'NULL') FROM demo_payment WHERE order_id=?")){ps.setLong(1,id);try(ResultSet rs=ps.executeQuery()){if(rs.next()){out("PAYMENT_ID",rs.getLong(1));out("PAYMENT_AMOUNT",rs.getBigDecimal(2));out("PAYMENT_STATUS",rs.getString(3));out("PAYMENT_PAID_AT",rs.getString(4));}}}
    }

    private static void callback(Connection c, String[] a) throws Exception {
        String callback=a[1];
        try(PreparedStatement ps=c.prepareStatement("SELECT COUNT(*) FROM demo_payment_callback WHERE callback_no=?")){ps.setString(1,callback);try(ResultSet rs=ps.executeQuery()){rs.next();out("CALLBACK_COUNT_FOR_ID",rs.getLong(1));}}
        try(PreparedStatement ps=c.prepareStatement("SELECT c.payment_id,c.callback_amount,c.process_status,c.result_code,COALESCE(DATE_FORMAT(c.received_at,'%Y-%m-%dT%H:%i:%s.%f'),'NULL'),COALESCE(DATE_FORMAT(c.processed_at,'%Y-%m-%dT%H:%i:%s.%f'),'NULL'),COALESCE(DATE_FORMAT(c.updated_at,'%Y-%m-%dT%H:%i:%s.%f'),'NULL'),p.order_id FROM demo_payment_callback c JOIN demo_payment p ON p.id=c.payment_id WHERE c.callback_no=?")){ps.setString(1,callback);try(ResultSet rs=ps.executeQuery()){if(rs.next()){out("CALLBACK_PAYMENT_ID",rs.getLong(1));out("CALLBACK_AMOUNT",rs.getBigDecimal(2));out("CALLBACK_PROCESS_STATUS",rs.getString(3));out("CALLBACK_RESULT_CODE",rs.getString(4));out("CALLBACK_RECEIVED_AT",rs.getString(5));out("CALLBACK_PROCESSED_AT",rs.getString(6));out("CALLBACK_UPDATED_AT",rs.getString(7));out("CALLBACK_ORDER_ID",rs.getLong(8));}}}
    }

    private static void cleanup(Connection c, String[] a) throws Exception {
        long order=Long.parseLong(a[1]), payment=Long.parseLong(a[2]), product=Long.parseLong(a[4]), stock=Long.parseLong(a[5]), userCoupon=Long.parseLong(a[6]);
        String callback=a[3], couponStatus=a[7], usedAt=a[8]; c.setAutoCommit(false);
        int n1=0,n2=0,n3,n4,n5;
        if(!"-".equals(callback)){try(PreparedStatement ps=c.prepareStatement("DELETE FROM demo_payment_callback WHERE callback_no=? AND payment_id=?")){ps.setString(1,callback);ps.setLong(2,payment);n1=ps.executeUpdate();}}
        if(payment>0){try(PreparedStatement ps=c.prepareStatement("DELETE FROM demo_payment WHERE id=? AND order_id=?")){ps.setLong(1,payment);ps.setLong(2,order);n2=ps.executeUpdate();}}
        try(PreparedStatement ps=c.prepareStatement("DELETE FROM demo_order_item WHERE order_id=?")){ps.setLong(1,order);n3=ps.executeUpdate();}
        try(PreparedStatement ps=c.prepareStatement("DELETE FROM demo_order WHERE id=?")){ps.setLong(1,order);n4=ps.executeUpdate();}
        try(PreparedStatement ps=c.prepareStatement("UPDATE demo_inventory SET available_stock=? WHERE product_id=?")){ps.setLong(1,stock);ps.setLong(2,product);n5=ps.executeUpdate();}
        int n6=0; if(userCoupon>0){try(PreparedStatement ps=c.prepareStatement("UPDATE demo_user_coupon SET status=?,used_at=? WHERE id=?")){ps.setString(1,couponStatus);if("NULL".equals(usedAt)){ps.setNull(2,Types.TIMESTAMP);}else{ps.setTimestamp(2,Timestamp.valueOf(usedAt.replace('T',' ')));}ps.setLong(3,userCoupon);n6=ps.executeUpdate();}}
        if(n1!=("-".equals(callback)?0:1)||n2!=(payment>0?1:0)||n3!=1||n4!=1||n5!=1||n6!=(userCoupon>0?1:0)) throw new IllegalStateException("cleanup row counts "+n1+","+n2+","+n3+","+n4+","+n5+","+n6);
        c.commit(); out("CLEANUP_OK",true);
    }

    public static void main(String[] args) throws Exception { try(Connection c=open()){ switch(args[0]){case "lookup"->lookup(c);case "snapshot"->snapshot(c,args);case "order"->order(c,args);case "callback"->callback(c,args);case "cleanup"->cleanup(c,args);default->throw new IllegalArgumentException("unknown mode");} } }
}
'@
$helperSourcePath = Join-Path $helperDir "E2eDbProbe.java"
Set-Content -LiteralPath $helperSourcePath -Value $helperSource -Encoding utf8
& javac.exe -cp $driverJar -d $helperDir $helperSourcePath
if ($LASTEXITCODE -ne 0) { throw "JDBC helper compilation failed" }

    $startedProcess = Start-Process -FilePath "java.exe" -ArgumentList @(
        "-jar", $jar.FullName, "--spring.profiles.active=local", "--server.port=0"
    ) -PassThru -RedirectStandardOutput (Join-Path $runtimeDir "application.stdout.log") -RedirectStandardError (Join-Path $runtimeDir "application.stderr.log") -WindowStyle Hidden
    $startedProcessId = $startedProcess.Id
    $stdoutPath = Join-Path $runtimeDir "application.stdout.log"
    $deadline = (Get-Date).AddSeconds(60)
    $actualPort = $null
    do {
        Start-Sleep -Milliseconds 250
        if ($startedProcess.HasExited) { throw "Application exited during startup" }
        $log = if (Test-Path $stdoutPath) { [string](Get-Content -LiteralPath $stdoutPath -Raw) } else { "" }
        $portMatch = [regex]::Match($log, 'Tomcat started on port (\d+)')
        if ($portMatch.Success -and $log -match 'Started DemoOrderApplication') { $actualPort = [int]$portMatch.Groups[1].Value }
    } while ($null -eq $actualPort -and (Get-Date) -lt $deadline)
    if ($null -eq $actualPort) { throw "Application startup timed out" }
    $baseUrl = "http://127.0.0.1:$actualPort"
    Write-Output "JAR_STARTED Profile=local Port=$actualPort"

    $ids = Invoke-DbProbe @("lookup")
    Assert-Equal $ids.PRODUCT1_STATUS "ON_SALE" "prd_001 status"
    Assert-Equal $ids.PRODUCT2_STATUS "ON_SALE" "prd_002 status"
    Assert-True ((As-Long $ids "PRODUCT1_ID") -lt (As-Long $ids "PRODUCT2_ID")) "prd_001 is processed before prd_002"

    $product = Invoke-Api "GET" ("/products/{0}" -f $ids.PRODUCT1_ID) "product-success" $null
    Assert-ApiEnvelope $product 200 $true "ORDER_SUCCESS" "product success"
    Assert-Equal $product.Body.data.productNo "prd_001" "product success productNo"

    $missing = Invoke-Api "GET" ("/products/{0}" -f $ids.MISSING_PRODUCT_ID) "product-missing" $null
    Assert-ApiEnvelope $missing 404 $false "ORDER_RESOURCE_NOT_FOUND" "product missing"
    Assert-Null $missing.Body.data "product missing data"

    $preNormal = Get-Snapshot $ids
    Assert-Equal (As-Long $preNormal "PRODUCT1_STOCK") 100 "normal order inventory baseline"
    Assert-Equal $preNormal.USER_COUPON_STATUS "AVAILABLE" "normal order user coupon baseline"
    $normalRequest = [ordered]@{ userId=[int64]$ids.USER_ID; items=@([ordered]@{productId=[int64]$ids.PRODUCT1_ID;quantity=1}); couponId=[int64]$ids.COUPON_ID }
    $normalRequestPath = Save-Json "normal-order-request.json" $normalRequest
    $normal = Invoke-Api "POST" "/orders" "normal-order" $normalRequestPath
    Assert-ApiEnvelope $normal 200 $true "ORDER_SUCCESS" "normal order"
    Assert-Equal $normal.Body.data.status "PENDING_PAYMENT" "normal order status"
    $expectedOriginal = [decimal]$ids.PRODUCT1_PRICE
    $expectedDiscount = if ($expectedOriginal -ge [decimal]$ids.COUPON_THRESHOLD) { [decimal]$ids.COUPON_DISCOUNT } else { [decimal]0 }
    $expectedPayable = $expectedOriginal - $expectedDiscount
    Assert-Equal ([decimal]$normal.Body.data.originalAmount) $expectedOriginal "normal order original amount"
    Assert-Equal ([decimal]$normal.Body.data.discountAmount) $expectedDiscount "normal order discount amount"
    Assert-Equal ([decimal]$normal.Body.data.payableAmount) $expectedPayable "normal order payable amount"
    $normalOrderId = [int64]$normal.Body.data.id
    $normalOrder = Invoke-DbProbe @("order", $normalOrderId)
    $normalResource = @{ ORDER_ID=$normalOrderId; PAYMENT_ID=(As-Long $normalOrder "PAYMENT_ID"); PRODUCT_ID=(As-Long $ids "PRODUCT1_ID"); INVENTORY_BEFORE=(As-Long $preNormal "PRODUCT1_STOCK"); USER_COUPON_ID=(As-Long $ids "USER_COUPON_ID"); COUPON_STATUS=$preNormal.USER_COUPON_STATUS; COUPON_USED_AT=$preNormal.USER_COUPON_USED_AT }
    Register-Resource $normalResource
    Assert-OrderState $normalOrder "PENDING_PAYMENT" $normalOrderId ([decimal]$normal.Body.data.payableAmount)
    Assert-Equal $normalOrder.ITEM_COUNT_FOR_ORDER 1 "normal order item count"
    Assert-Equal $normalOrder.PAYMENT_STATUS "PENDING" "normal order payment status"
    Assert-Equal $normalOrder.ORDER_USER_COUPON_ID $ids.USER_COUPON_ID "normal order user coupon id"
    $normalAfter = Get-Snapshot $ids
    Assert-Equal (As-Long $normalAfter "PRODUCT1_STOCK") 99 "normal order inventory deduction"
    Assert-Equal $normalAfter.USER_COUPON_STATUS "USED" "normal order coupon consumption"
    Cleanup-Resource $normalResource

    $preInventory = Get-Snapshot $ids
    $singleRequest = [ordered]@{ userId=[int64]$ids.USER_ID; items=@([ordered]@{productId=[int64]$ids.PRODUCT2_ID;quantity=3}) }
    $singleRequestPath = Save-Json "single-inventory-failure-request.json" $singleRequest
    $single = Invoke-Api "POST" "/orders" "single-inventory-failure" $singleRequestPath
    Assert-ApiEnvelope $single 409 $false "ORDER_BUSINESS_CONFLICT" "single inventory failure"
    Assert-True ([string]$single.Body.message -match "insufficient inventory.*$($ids.PRODUCT2_ID)") "single inventory message"
    Assert-Null $single.Body.data "single inventory data"
    $singleAfter = Get-Snapshot $ids
    Assert-Equal (As-Long $singleAfter "PRODUCT2_STOCK") 2 "single inventory unchanged"
    Assert-CountsUnchanged $preInventory $singleAfter "single inventory rollback snapshot"

    $preMulti = Get-Snapshot $ids
    $multiRequest = [ordered]@{ userId=[int64]$ids.USER_ID; items=@([ordered]@{productId=[int64]$ids.PRODUCT1_ID;quantity=1},[ordered]@{productId=[int64]$ids.PRODUCT2_ID;quantity=3}) }
    $multiRequestPath = Save-Json "multi-inventory-rollback-request.json" $multiRequest
    $multi = Invoke-Api "POST" "/orders" "multi-inventory-rollback" $multiRequestPath
    Assert-ApiEnvelope $multi 409 $false "ORDER_BUSINESS_CONFLICT" "multi inventory failure"
    Assert-True ([string]$multi.Body.message -match "insufficient inventory.*$($ids.PRODUCT2_ID)") "multi inventory message"
    Assert-Null $multi.Body.data "multi inventory data"
    $multiAfter = Get-Snapshot $ids
    Assert-Equal (As-Long $multiAfter "PRODUCT1_STOCK") 100 "multi inventory first item rollback"
    Assert-Equal (As-Long $multiAfter "PRODUCT2_STOCK") 2 "multi inventory second item unchanged"
    Assert-CountsUnchanged $preMulti $multiAfter "multi inventory rollback snapshot"

    $preCancel = Get-Snapshot $ids
    $cancelRequest = [ordered]@{ userId=[int64]$ids.USER_ID; items=@([ordered]@{productId=[int64]$ids.PRODUCT1_ID;quantity=1}) }
    $cancelRequestPath = Save-Json "cancel-order-request.json" $cancelRequest
    $cancelCreate = Invoke-Api "POST" "/orders" "cancel-create" $cancelRequestPath
    Assert-ApiEnvelope $cancelCreate 200 $true "ORDER_SUCCESS" "cancel create"
    Assert-Equal $cancelCreate.Body.data.status "PENDING_PAYMENT" "cancel initial status"
    $cancelOrderId = [int64]$cancelCreate.Body.data.id
    $cancelOrder = Invoke-DbProbe @("order", $cancelOrderId)
    $cancelResource = @{ ORDER_ID=$cancelOrderId; PAYMENT_ID=(As-Long $cancelOrder "PAYMENT_ID"); PRODUCT_ID=(As-Long $ids "PRODUCT1_ID"); INVENTORY_BEFORE=(As-Long $preCancel "PRODUCT1_STOCK") }
    Register-Resource $cancelResource
    $cancelFirst = Invoke-Api "POST" ("/orders/{0}/cancel" -f $cancelOrderId) "cancel-first" $null
    Assert-ApiEnvelope $cancelFirst 200 $true "ORDER_SUCCESS" "cancel first"
    Assert-Equal $cancelFirst.Body.data.status "CANCELLED" "cancel first status"
    $cancelAfterFirst = Invoke-DbProbe @("order", $cancelOrderId)
    Assert-Equal $cancelAfterFirst.ORDER_STATUS "CANCELLED" "cancelled order status"
    Assert-Equal $cancelAfterFirst.PAYMENT_STATUS "PENDING" "cancelled payment status"
    $cancelSecond = Invoke-Api "POST" ("/orders/{0}/cancel" -f $cancelOrderId) "cancel-second" $null
    Assert-ApiEnvelope $cancelSecond 409 $false "ORDER_BUSINESS_CONFLICT" "cancel second"
    Assert-True ([string]$cancelSecond.Body.message -match "status conflict") "cancel second message"
    Assert-Null $cancelSecond.Body.data "cancel second data"
    $cancelAfterSecond = Invoke-DbProbe @("order", $cancelOrderId)
    Assert-Equal $cancelAfterSecond.ORDER_STATUS "CANCELLED" "repeat cancel final state"
    $cancelGet = Invoke-Api "GET" ("/orders/{0}" -f $cancelOrderId) "cancel-final-get" $null
    Assert-ApiEnvelope $cancelGet 200 $true "ORDER_SUCCESS" "cancel final get"
    Assert-Equal $cancelGet.Body.data.status "CANCELLED" "cancel final GET state"
    Cleanup-Resource $cancelResource

    $prePayment = Get-Snapshot $ids
    $paymentCreateRequest = [ordered]@{ userId=[int64]$ids.USER_ID; items=@([ordered]@{productId=[int64]$ids.PRODUCT1_ID;quantity=1}) }
    $paymentCreatePath = Save-Json "payment-order-request.json" $paymentCreateRequest
    $paymentCreate = Invoke-Api "POST" "/orders" "payment-create" $paymentCreatePath
    Assert-ApiEnvelope $paymentCreate 200 $true "ORDER_SUCCESS" "payment create"
    Assert-Equal $paymentCreate.Body.data.status "PENDING_PAYMENT" "payment initial status"
    $paymentOrderId = [int64]$paymentCreate.Body.data.id
    $paymentOrder = Invoke-DbProbe @("order", $paymentOrderId)
    $paymentId = As-Long $paymentOrder "PAYMENT_ID"
    Assert-Equal $paymentOrder.PAYMENT_STATUS "PENDING" "payment initial record status"
    Assert-Equal ([decimal]$paymentOrder.PAYMENT_AMOUNT) ([decimal]$paymentCreate.Body.data.payableAmount) "payment amount"
    $callbackId = "e2e-script-" + ([guid]::NewGuid().ToString("N"))
    $callbackTime = (Get-Date).ToString("yyyy-MM-ddTHH:mm:ss")
    $callbackRequest = [ordered]@{ callbackId=$callbackId; paymentId=$paymentId; orderId=$paymentOrderId; paymentAmount=[decimal]$paymentOrder.PAYMENT_AMOUNT; result="SUCCESS"; callbackTime=$callbackTime }
    $callbackPath = Save-Json "payment-callback-request.json" $callbackRequest
    $paymentResource = @{ ORDER_ID=$paymentOrderId; PAYMENT_ID=$paymentId; CALLBACK_ID=$callbackId; PRODUCT_ID=(As-Long $ids "PRODUCT1_ID"); INVENTORY_BEFORE=(As-Long $prePayment "PRODUCT1_STOCK") }
    Register-Resource $paymentResource
    $callbackFirst = Invoke-Api "POST" "/payments/callback" "payment-callback-first" $callbackPath
    Assert-ApiEnvelope $callbackFirst 200 $true "ORDER_SUCCESS" "payment first callback"
    Assert-Equal $callbackFirst.Body.data.outcome "FIRST_SUCCESS" "payment first outcome"
    Assert-Equal $callbackFirst.Body.data.replay $false "payment first replay"
    Assert-Equal $callbackFirst.Body.data.callbackId $callbackId "payment first callback id"
    $paymentAfterFirst = Invoke-DbProbe @("order", $paymentOrderId)
    $callbackAfterFirst = Invoke-DbProbe @("callback", $callbackId)
    Assert-Equal $paymentAfterFirst.ORDER_STATUS "PAID" "payment first order status"
    Assert-Equal $paymentAfterFirst.PAYMENT_STATUS "SUCCESS" "payment first payment status"
    Assert-True ($callbackAfterFirst.CALLBACK_COUNT_FOR_ID -eq "1") "payment first callback count"
    Assert-Equal $callbackAfterFirst.CALLBACK_PROCESS_STATUS "SUCCESS" "payment callback process status"
    Assert-Equal $callbackAfterFirst.CALLBACK_ORDER_ID $paymentOrderId "payment callback order relation"
    $callbackReplay = Invoke-Api "POST" "/payments/callback" "payment-callback-replay" $callbackPath
    Assert-ApiEnvelope $callbackReplay 200 $true "ORDER_SUCCESS" "payment replay callback"
    Assert-Equal $callbackReplay.Body.data.outcome "IDEMPOTENT_REPLAY" "payment replay outcome"
    Assert-Equal $callbackReplay.Body.data.replay $true "payment replay flag"
    Assert-Equal $callbackReplay.Body.data.callbackId $callbackId "payment replay callback id"
    $paymentAfterReplay = Invoke-DbProbe @("order", $paymentOrderId)
    $callbackAfterReplay = Invoke-DbProbe @("callback", $callbackId)
    Assert-Equal $paymentAfterReplay.ORDER_STATUS "PAID" "payment replay order status"
    Assert-Equal $paymentAfterReplay.PAYMENT_STATUS "SUCCESS" "payment replay payment status"
    Assert-Equal $paymentAfterReplay.PAYMENT_COUNT_FOR_ORDER 1 "payment replay payment count"
    Assert-Equal $callbackAfterReplay.CALLBACK_COUNT_FOR_ID 1 "payment replay callback count"
    $paymentGet = Invoke-Api "GET" ("/orders/{0}" -f $paymentOrderId) "payment-final-get" $null
    Assert-ApiEnvelope $paymentGet 200 $true "ORDER_SUCCESS" "payment final get"
    Assert-Equal $paymentGet.Body.data.status "PAID" "payment final GET state"
    Cleanup-Resource $paymentResource

    $tokenMeta = [ordered]@{ method="POST"; path="/api/faults/token-expired"; body=$null }
    $tokenMetaPath = Save-Json "token-expired-request.json" $tokenMeta
    $token = Invoke-Api "POST" "/api/faults/token-expired" "token-expired" $null
    Assert-ApiEnvelope $token 401 $false "ORDER_TOKEN_EXPIRED" "token expired"
    Assert-Equal $token.Body.message "token expired" "token expired message"
    Assert-Null $token.Body.data "token expired data"

    $slowDefault = Invoke-Api "GET" "/api/faults/slow-sql" "slow-sql-default" $null
    Assert-ApiEnvelope $slowDefault 200 $true "ORDER_SUCCESS" "slow SQL default"
    Assert-Equal $slowDefault.Body.data.requestedDelayMs 500 "slow SQL default delay"
    Assert-True ([int64]$slowDefault.Body.data.elapsedMs -ge 500) "slow SQL default server elapsed"
    Assert-True ($slowDefault.ClientElapsedMs -ge 500) "slow SQL default client elapsed"
    Save-Json "slow-sql-default-timing.json" ([ordered]@{ request="GET /api/faults/slow-sql"; clientElapsedMs=$slowDefault.ClientElapsedMs; response=$slowDefault.Body }) | Out-Null

    $slow300 = Invoke-Api "GET" "/api/faults/slow-sql?delayMs=300" "slow-sql-300" $null
    Assert-ApiEnvelope $slow300 200 $true "ORDER_SUCCESS" "slow SQL 300"
    Assert-Equal $slow300.Body.data.requestedDelayMs 300 "slow SQL 300 delay"
    Assert-True ([int64]$slow300.Body.data.elapsedMs -ge 300) "slow SQL 300 server elapsed"
    Assert-True ($slow300.ClientElapsedMs -ge 300) "slow SQL 300 client elapsed"
    Save-Json "slow-sql-300-timing.json" ([ordered]@{ request="GET /api/faults/slow-sql?delayMs=300"; clientElapsedMs=$slow300.ClientElapsedMs; response=$slow300.Body }) | Out-Null

    $slowInvalid = Invoke-Api "GET" "/api/faults/slow-sql?delayMs=99" "slow-sql-invalid-99" $null
    Assert-ApiEnvelope $slowInvalid 400 $false "ORDER_PARAM_INVALID" "slow SQL invalid delay"
    Assert-Null $slowInvalid.Body.data "slow SQL invalid data"
    Save-Json "slow-sql-invalid-99-timing.json" ([ordered]@{ request="GET /api/faults/slow-sql?delayMs=99"; clientElapsedMs=$slowInvalid.ClientElapsedMs; response=$slowInvalid.Body }) | Out-Null

    $hikariDeadline = (Get-Date).AddSeconds(30)
    do { Start-Sleep -Milliseconds 200; $runtimeLog = [string](Get-Content -LiteralPath $stdoutPath -Raw) } while ($runtimeLog -notmatch 'HikariPool-1 - Start completed' -and (Get-Date) -lt $hikariDeadline)
    if ($runtimeLog -notmatch 'HikariPool-1 - Start completed') { throw "Hikari initialization was not observed in application log" }

    $final = Get-Snapshot $ids
    Assert-Equal (As-Long $final "PRODUCT1_STOCK") 100 "final product1 inventory"
    Assert-Equal (As-Long $final "PRODUCT2_STOCK") 2 "final product2 inventory"
    Assert-Equal $final.USER_COUPON_STATUS "AVAILABLE" "final user coupon status"
    Write-Output "E2E PASS: product query, order transaction, inventory failures/rollback, cancel conflict, payment idempotency, token fault, slow SQL and parameter validation"
    Write-Output ("SLOW SQL: default service={0}ms client={1}ms; 300ms service={2}ms client={3}ms; invalid client={4}ms" -f $slowDefault.Body.data.elapsedMs, $slowDefault.ClientElapsedMs, $slow300.Body.data.elapsedMs, $slow300.ClientElapsedMs, $slowInvalid.ClientElapsedMs)
}
catch {
    $scriptFailure = $_
    Write-Error $_
}
finally {
    foreach ($resource in @($activeResources.ToArray())) {
        try { Cleanup-Resource $resource } catch { [void]$cleanupErrors.Add($_.Exception.Message) }
    }
    if ($null -ne $startedProcessId) {
        $process = Get-CimInstance Win32_Process -Filter "ProcessId = $startedProcessId" -ErrorAction SilentlyContinue
        if ($null -ne $process -and $process.CommandLine -match ([regex]::Escape($jar.Name))) {
            Stop-Process -Id $startedProcessId -Force -ErrorAction SilentlyContinue
        }
    }
    if ($null -ne $jar) {
        $remaining = @(Get-ModuleJarProcesses $jar.Name)
        if ($remaining.Count -gt 0) {
            $remaining | ForEach-Object { Write-Error "Matching module JAR process remains: $($_.ProcessId)" }
            if ($cleanupErrors.Count -eq 0) { [void]$cleanupErrors.Add("matching JAR process remains") }
        }
    }
    if ($cleanupErrors.Count -gt 0) {
        $cleanupErrors | ForEach-Object { Write-Error $_ }
    }
}

if ($null -ne $scriptFailure -or $cleanupErrors.Count -gt 0) {
    exit 1
}
