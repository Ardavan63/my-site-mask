export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    // اگر به انتهای لینک توکن نداده بود، خطا ندهد
    const path = url.pathname.split('/');
    const token = path[path.length - 1]; 

    // 1. بررسی امنیتی: فقط مسیرهای /sub/ را قبول کن
    if (!url.pathname.startsWith('/sub/')) {
      return new Response('Access Denied', { status: 403 });
    }

    // 2. چک کردن توکن در دیتابیس کاربران
    // اگر توکن خالی یا اشتباه بود، ارور بدهد
    if (!token || token === 'sub') {
         return new Response('Invalid Token', { status: 400 });
    }

    const user = await env.USERS_DB.get(token);
    if (!user) {
      return new Response('Invalid Subscription', { status: 404 });
    }

    // 3. گرفتن کانفیگ‌ها از دیتابیس (۱۴ تا رندوم)
    const allConfigs = await env.CONFIGS_DB.list();
    // اگر کانفیگی نبود، خطا ندهد
    if (!allConfigs.keys || allConfigs.keys.length === 0) {
        return new Response('No configs available', { status: 503 });
    }

    const shuffled = allConfigs.keys.sort(() => 0.5 - Math.random());
    const selected = shuffled.slice(0, 14);

    let output = "";
    for (const key of selected) {
      const config = await env.CONFIGS_DB.get(key.name);
      if (config) {
          output += config + "\n";
      }
    }

    // 4. خروجی نهایی به صورت Base64
    return new Response(btoa(output), {
      headers: { 'content-type': 'text/plain; charset=utf-8' }
    });
  }
};
