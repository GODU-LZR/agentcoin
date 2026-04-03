import {notFound} from 'next/navigation';
import {getRequestConfig} from 'next-intl/server';

const locales = ['en', 'zh', 'ja'];

export default getRequestConfig(async (args: any) => {
  let locale = args.locale;
  
  if (!locale && args.requestLocale) {
    locale = await args.requestLocale;
  }

  if (!locale || typeof locale !== 'string') {
    locale = 'en';
  }

  if (!locales.includes(locale)) {
    notFound();
  }

  try {
    const msgs = (await import(`./messages/${locale}.json`)).default;
    return { locale, messages: msgs };
  } catch (err) {
    notFound();
  }
});