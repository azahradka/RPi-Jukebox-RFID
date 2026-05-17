import React from 'react';
import { screen } from '@testing-library/react';

import { renderWithProviders } from './renderWithProviders';
import {
  __setMockResponse,
  __mockSocketLog,
  __resetMockSocket,
  __publishMockMessage,
  socketRequest as mockSocketRequest,
} from './mockSocket';

jest.mock('../sockets', () => require('./mockSocket'));
jest.mock('../utils/request', () => ({
  __esModule: true,
  default: jest.fn(() => Promise.resolve({ result: {} })),
}));

describe('test-utils smoke', () => {
  beforeEach(() => {
    __resetMockSocket();
  });

  test('renderWithProviders mounts a trivial child', () => {
    renderWithProviders(<div data-testid="hello">hi</div>);
    expect(screen.getByTestId('hello')).toHaveTextContent('hi');
  });

  test('mockSocket exposes the expected mock surface', () => {
    expect(typeof mockSocketRequest).toBe('function');
    expect(Array.isArray(__mockSocketLog)).toBe(true);
    expect(typeof __setMockResponse).toBe('function');
    expect(typeof __publishMockMessage).toBe('function');
  });

  test('__setMockResponse routes socketRequest response', async () => {
    __setMockResponse('player.ctrl.play', { ok: true });
    const result = await mockSocketRequest('player', 'ctrl', 'play', {});
    expect(result).toEqual({ ok: true });
    expect(__mockSocketLog).toEqual([{ key: 'player.ctrl.play', kwargs: {} }]);
  });

  test('socketRequest resolves undefined when no response configured', async () => {
    const result = await mockSocketRequest('unknown', 'plugin', 'method', {});
    expect(result).toBeUndefined();
  });
});
