from django import template

register = template.Library()

@register.filter
def median_price(pricing_qs):
    prices = [r.cash_price for r in pricing_qs if r.cash_price]
    if not prices:
        return "N/A"
    prices.sort()
    n = len(prices)
    if n % 2 == 0:
        median = (prices[n//2 - 1] + prices[n//2]) / 2
    else:
        median = prices[n//2]
    return f"{median:,.0f}"
