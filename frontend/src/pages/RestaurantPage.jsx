import React from 'react';
import { Header } from '../components/layout/Header';
import { BottomNav } from '../components/layout/BottomNav';
import { RestaurantSession } from '../components/restaurant/RestaurantSession';

export default function RestaurantPage() {
  return (
    <div className="page" style={{ background: '#f8fafc', minHeight: '100vh' }}>
      <Header title="Sesión restaurante" />
      <main style={{ padding: '1rem', paddingBottom: '5rem' }}>
        <RestaurantSession />
      </main>
      <BottomNav />
    </div>
  );
}
