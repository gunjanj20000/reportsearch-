import React, { useState, useEffect } from 'react';
import { Download, X, Share, PlusSquare } from 'lucide-react';

export const InstallPrompt: React.FC = () => {
  const [deferredPrompt, setDeferredPrompt] = useState<any>(null);
  const [showIosPrompt, setShowIosPrompt] = useState(false);
  const [dismissed, setDismissed] = useState(false);

  useEffect(() => {
    // Check if already in standalone PWA mode
    const isStandalone = window.matchMedia('(display-mode: standalone)').matches ||
      (window.navigator as any).standalone;

    if (isStandalone) return;

    // Android / Chrome beforeinstallprompt
    const handleBeforeInstall = (e: Event) => {
      e.preventDefault();
      setDeferredPrompt(e);
    };
    window.addEventListener('beforeinstallprompt', handleBeforeInstall);

    // iOS Safari detection
    const isIos = /iphone|ipad|ipod/i.test(navigator.userAgent);
    const isSafari = /safari/i.test(navigator.userAgent) && !/chrome|crios/i.test(navigator.userAgent);

    if (isIos && isSafari && !sessionStorage.getItem('medsearch_pwa_ios_dismissed')) {
      setShowIosPrompt(true);
    }

    return () => {
      window.removeEventListener('beforeinstallprompt', handleBeforeInstall);
    };
  }, []);

  const handleInstallClick = async () => {
    if (!deferredPrompt) return;
    deferredPrompt.prompt();
    const { outcome } = await deferredPrompt.userChoice;
    if (outcome === 'accepted') {
      setDeferredPrompt(null);
    }
  };

  const handleDismiss = () => {
    setDismissed(true);
    setShowIosPrompt(false);
    sessionStorage.setItem('medsearch_pwa_ios_dismissed', 'true');
  };

  if (dismissed) return null;

  // Android prompt
  if (deferredPrompt) {
    return (
      <div className="fixed bottom-3 inset-x-3 sm:inset-x-auto sm:right-4 z-40 max-w-sm bg-slate-900 border border-sky-500/40 rounded-2xl p-3.5 shadow-2xl flex items-center justify-between gap-3 animate-slide-up">
        <div className="flex items-center space-x-2.5">
          <div className="w-9 h-9 rounded-xl bg-sky-500/20 border border-sky-400/40 flex items-center justify-center text-sky-400 shrink-0">
            <Download className="w-4 h-4" />
          </div>
          <div>
            <h4 className="text-xs font-bold text-slate-100">Install Offline App</h4>
            <p className="text-[11px] text-slate-400">Search anytime without internet</p>
          </div>
        </div>
        <div className="flex items-center space-x-1.5 shrink-0">
          <button
            onClick={handleInstallClick}
            className="px-3 py-1.5 rounded-xl bg-sky-500 hover:bg-sky-400 text-slate-950 font-bold text-xs transition-colors"
          >
            Install
          </button>
          <button
            onClick={handleDismiss}
            className="p-1.5 text-slate-400 hover:text-slate-200"
          >
            <X className="w-4 h-4" />
          </button>
        </div>
      </div>
    );
  }

  // iOS Safari prompt
  if (showIosPrompt) {
    return (
      <div className="fixed bottom-3 inset-x-3 sm:inset-x-auto sm:right-4 z-40 max-w-sm bg-slate-900 border border-slate-700 rounded-2xl p-3.5 shadow-2xl space-y-2 animate-slide-up">
        <div className="flex items-start justify-between">
          <div className="flex items-center space-x-2">
            <PlusSquare className="w-4 h-4 text-sky-400" />
            <span className="text-xs font-bold text-slate-100">Install on iPhone / iPad</span>
          </div>
          <button onClick={handleDismiss} className="text-slate-400 hover:text-slate-200">
            <X className="w-4 h-4" />
          </button>
        </div>
        <p className="text-[11px] text-slate-400 leading-relaxed">
          Tap <Share className="w-3.5 h-3.5 inline text-sky-400 mx-0.5" /> in Safari menu, then select{' '}
          <strong className="text-slate-200">"Add to Home Screen"</strong> for instant full-screen offline access.
        </p>
      </div>
    );
  }

  return null;
};
