import django.core.validators
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models

# A generated AddField emits "ALTER COLUMN ... DROP DEFAULT", which the production Postgres
# rejects, so the columns are added by hand with their defaults left in place, as in 0030.


def add_equity_pricing_fields(_apps, schema_editor):
    is_postgres = schema_editor.connection.vendor == "postgresql"
    schema_editor.execute(
        'ALTER TABLE "career_offer" ADD COLUMN "equity_ticker" varchar(12) NOT NULL DEFAULT \'\';'
    )
    numeric = "numeric" if is_postgres else "decimal"
    schema_editor.execute(
        f'ALTER TABLE "career_offer" ADD COLUMN "equity_shares" {numeric}(14, 4) NULL;'
    )
    schema_editor.execute(
        f'ALTER TABLE "career_offer" ADD COLUMN "equity_grant_price" {numeric}(12, 4) NULL;'
    )


def drop_equity_pricing_fields(_apps, schema_editor):
    for column in ("equity_ticker", "equity_shares", "equity_grant_price"):
        schema_editor.execute(f'ALTER TABLE "career_offer" DROP COLUMN "{column}";')


class Migration(migrations.Migration):
    dependencies = [
        ("career", "0036_drop_exclude_allowances"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.AddField(
                    model_name="offer",
                    name="equity_ticker",
                    field=models.CharField(
                        blank=True,
                        help_text="Ticker whose latest price reprices this grant, e.g. GOOG",
                        max_length=12,
                    ),
                ),
                migrations.AddField(
                    model_name="offer",
                    name="equity_shares",
                    field=models.DecimalField(
                        blank=True,
                        decimal_places=4,
                        help_text="Total shares in the grant, if known",
                        max_digits=14,
                        null=True,
                    ),
                ),
                migrations.AddField(
                    model_name="offer",
                    name="equity_grant_price",
                    field=models.DecimalField(
                        blank=True,
                        decimal_places=4,
                        help_text="Price per share when the grant was made",
                        max_digits=12,
                        null=True,
                    ),
                ),
            ],
            database_operations=[
                migrations.RunPython(add_equity_pricing_fields, drop_equity_pricing_fields),
            ],
        ),
        migrations.CreateModel(
            name="StockPrice",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("symbol", models.CharField(help_text="Ticker, stored uppercase", max_length=12)),
                (
                    "price",
                    models.DecimalField(
                        decimal_places=4,
                        max_digits=12,
                        validators=[django.core.validators.MinValueValidator(0)],
                    ),
                ),
                ("as_of", models.DateField(help_text="The date this price is good for")),
                (
                    "source",
                    models.CharField(
                        choices=[("MANUAL", "Entered by hand"), ("API", "Fetched from a market data provider")],
                        default="MANUAL",
                        max_length=10,
                    ),
                ),
                ("note", models.CharField(blank=True, max_length=200)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "user",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="stock_prices",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={"ordering": ["symbol"]},
        ),
        migrations.AddConstraint(
            model_name="stockprice",
            constraint=models.UniqueConstraint(
                fields=("user", "symbol"), name="unique_stock_price_per_user_symbol"
            ),
        ),
    ]
