/**
 * Tests to verify FinSyntra AI branding is applied
 */

import React from 'react';
import { render, screen } from '@testing-library/react';
import { BrowserRouter } from 'react-router-dom';
import Hero from '../components/Hero';

describe('FinSyntra AI Branding', () => {
  test('Hero component includes FinSyntra branding', () => {
    const mockUser = { name: 'Test User' };
    const mockOnCategorySelect = jest.fn();

    render(
      <BrowserRouter>
        <Hero user={mockUser} onCategorySelect={mockOnCategorySelect} />
      </BrowserRouter>
    );

    // Check for marketing hero text
    expect(screen.getByText(/Welcome to FinSyntra/i)).toBeInTheDocument();
    expect(screen.getByText(/grounded in your data/i)).toBeInTheDocument();
    expect(screen.getByText(/Grounded answers from your own documents/i)).toBeInTheDocument();

    // Check for original greeting still present
    expect(screen.getByText(/Hey! Test/i)).toBeInTheDocument();
    expect(screen.getByText(/What can I help with/i)).toBeInTheDocument();
  });

  test('Hero component renders logo image', () => {
    const mockUser = { name: 'Test User' };
    const mockOnCategorySelect = jest.fn();

    render(
      <BrowserRouter>
        <Hero user={mockUser} onCategorySelect={mockOnCategorySelect} />
      </BrowserRouter>
    );

    // Check for logo image (now uses PNG-based Logo component)
    const logoImage = screen.getByAltText('FinSyntra AI');
    expect(logoImage).toBeInTheDocument();
  });

  test('Hero component renders quick action categories', () => {
    const mockUser = { name: 'Test User' };
    const mockOnCategorySelect = jest.fn();

    render(
      <BrowserRouter>
        <Hero user={mockUser} onCategorySelect={mockOnCategorySelect} />
      </BrowserRouter>
    );

    // Check that the role-oriented quick actions are present
    expect(screen.getByText(/Finance/i)).toBeInTheDocument();
    expect(screen.getByText(/HR & Policy/i)).toBeInTheDocument();
    expect(screen.getByText(/Leadership/i)).toBeInTheDocument();
  });
});

