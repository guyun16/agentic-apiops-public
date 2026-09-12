# Catalog service reference

The Catalog service publishes product names, categories, descriptions, prices,
and display stock. Catalog reads are cacheable and do not describe Orders
database constraints or customer references.

This document is a distractor for an Orders duplicate-key investigation. A
zero display-stock value is informational; inventory reservation belongs to
the Inventory service. Do not use Catalog metadata as Orders incident evidence.
